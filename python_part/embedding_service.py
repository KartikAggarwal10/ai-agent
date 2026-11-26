"""
embedding_service.py
====================
Embeddings and Hybrid Retrieval Service for handling large pasted documents (>20 lines),
following the exact architecture implemented in embeddings.py:

Pipeline:
  1. Chunking: RecursiveCharacterTextSplitter (chunk_size=500, chunk_overlap=100)
  2. Embeddings: HuggingFaceEmbeddings (using local embedding_model)
  3. Vector Store: FAISS (saved/loaded from vectorstore)
  4. Sparse Retrieval: BM25Retriever (top-k=20)
  5. Dense Retrieval: FAISS vector_retriever (top-k=20)
  6. Hybrid Retrieval: EnsembleRetriever (weights [0.5, 0.5])
  7. Reranking: CrossEncoderReranker (BAAI/bge-reranker-base, top_n=5)
  8. Contextual Compression: ContextualCompressionRetriever
  9. Generation: LLM (Google AI Studio/Gemini/Groq/etc.) with local pipeline fallback
"""

import os
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Resolve directory paths reliably regardless of execution working directory
CURRENT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = CURRENT_DIR.parent

# Detect embedding_model path
if (CURRENT_DIR / "embedding_model").exists():
    EMBEDDING_MODEL_PATH = str(CURRENT_DIR / "embedding_model")
elif (WORKSPACE_DIR / "embedding_model").exists():
    EMBEDDING_MODEL_PATH = str(WORKSPACE_DIR / "embedding_model")
elif os.path.exists("./embedding_model"):
    EMBEDDING_MODEL_PATH = "./embedding_model"
else:
    EMBEDDING_MODEL_PATH = "sentence-transformers/all-MiniLM-L6-v2"

# Detect vectorstore path
if (CURRENT_DIR / "vectorstore").exists():
    VECTORSTORE_PATH = str(CURRENT_DIR / "vectorstore")
elif (WORKSPACE_DIR / "vectorstore").exists():
    VECTORSTORE_PATH = str(WORKSPACE_DIR / "vectorstore")
else:
    VECTORSTORE_PATH = str(CURRENT_DIR / "vectorstore")


from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_classic.retrievers import ContextualCompressionRetriever
from transformers import pipeline


def count_lines(text: str) -> int:
    """Return the number of lines in text."""
    if not text:
        return 0
    return len(text.strip().splitlines())


def is_more_than_20_lines(text: str) -> bool:
    """Check if the text has strictly more than 20 lines."""
    return count_lines(text) > 20


class EmbeddingService:
    def __init__(self):
        print(f"[INFO] Initializing EmbeddingService with model: {EMBEDDING_MODEL_PATH}")
        self.embedding = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_PATH
        )

        # Vector DB load or create
        self.db = None
        self.compression = None
        self.vector_retriever = None
        self.bm25 = None
        self.ensemble = None
        self.reranker = None
        self.generator = None

        self._init_vectorstore()
        self._init_reranker()
        self._init_generator()
        self.rebuild_retrievers()

    def _init_vectorstore(self):
        try:
            if os.path.exists(VECTORSTORE_PATH) and (
                os.path.exists(os.path.join(VECTORSTORE_PATH, "index.faiss")) or
                os.path.exists(os.path.join(VECTORSTORE_PATH, "index.pkl"))
            ):
                print(f"[INFO] Loading existing vectorstore from: {VECTORSTORE_PATH}")
                self.db = FAISS.load_local(
                    VECTORSTORE_PATH,
                    self.embedding,
                    allow_dangerous_deserialization=True
                )
            else:
                print(f"[INFO] No existing vectorstore found at {VECTORSTORE_PATH}, will create on first document.")
                self.db = None
        except Exception as e:
            print(f"[WARNING] Could not load vectorstore from {VECTORSTORE_PATH}: {e}")
            self.db = None

    def _init_reranker(self):
        try:
            reranker_model = HuggingFaceCrossEncoder(
                model_name="BAAI/bge-reranker-base"
            )
            self.reranker = CrossEncoderReranker(
                model=reranker_model,
                top_n=5
            )
        except Exception as e:
            print(f"[WARNING] Could not load CrossEncoder reranker BAAI/bge-reranker-base: {e}")
            self.reranker = None

    def _init_generator(self):
        try:
            self.generator = pipeline(
                "text-generation",
                model="distilgpt2"
            )
        except Exception as e:
            print(f"[WARNING] Could not initialize fallback pipeline generator: {e}")
            self.generator = None

    def rebuild_retrievers(self):
        """Rebuild BM25, Vector Retriever, Ensemble, and ContextualCompressionRetriever."""
        if self.db is None:
            self.compression = None
            return

        try:
            docs = self.db.similarity_search("", k=1000)
            if not docs:
                self.compression = None
                return

            k_val = min(20, max(1, len(docs)))
            self.vector_retriever = self.db.as_retriever(
                search_kwargs={"k": k_val}
            )

            self.bm25 = BM25Retriever.from_documents(docs)
            self.bm25.k = k_val

            self.ensemble = EnsembleRetriever(
                retrievers=[
                    self.vector_retriever,
                    self.bm25
                ],
                weights=[0.5, 0.5]
            )

            if self.reranker:
                self.compression = ContextualCompressionRetriever(
                    base_retriever=self.ensemble,
                    base_compressor=self.reranker
                )
            else:
                self.compression = self.ensemble

            print(f"[INFO] Retrievers successfully rebuilt with {len(docs)} document chunks.")
        except Exception as e:
            print(f"[ERROR] Failed to rebuild retrievers: {e}")
            self.compression = None

    def chunk_text(self, text: str) -> List[Document]:
        """Split text using RecursiveCharacterTextSplitter (chunk_size=500, chunk_overlap=100)."""
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=500,
                chunk_overlap=100
            )
            return splitter.create_documents([text])
        except Exception:
            # Resilient fallback if text splitters package imports differently
            chunks = []
            step = 400
            for i in range(0, len(text), step):
                chunk = text[i:i + 500].strip()
                if chunk:
                    chunks.append(chunk)
            return [Document(page_content=c) for c in chunks]

    def ingest_pasted_text(self, text: str) -> List[Document]:
        """
        Ingest pasted text with > 20 lines into the FAISS vector database.
        Saves updated vector database to disk and refreshes the retrieval pipeline.
        """
        documents = self.chunk_text(text)
        if not documents:
            return []

        print(f"[INFO] Chunked pasted text into {len(documents)} chunks.")

        if self.db is None:
            self.db = FAISS.from_documents(documents, self.embedding)
        else:
            self.db.add_documents(documents)

        # Persist vectorstore to disk
        try:
            os.makedirs(VECTORSTORE_PATH, exist_ok=True)
            self.db.save_local(VECTORSTORE_PATH)
            print(f"[INFO] Persisted updated vectorstore to {VECTORSTORE_PATH}")
        except Exception as e:
            print(f"[WARNING] Could not save vectorstore locally: {e}")

        # Rebuild retrievers with the new documents
        self.rebuild_retrievers()
        return documents

    def retrieve_context(self, query: str) -> List[Document]:
        """Retrieve the top matching document chunks using ContextualCompressionRetriever."""
        if self.compression is None:
            if self.db is not None:
                return self.db.similarity_search(query, k=5)
            return []
        try:
            return self.compression.invoke(query)
        except Exception as e:
            print(f"[WARNING] Compression retriever failed, falling back to db search: {e}")
            if self.db is not None:
                return self.db.similarity_search(query, k=5)
            return []

    def answer_query(self, query: str, context: Optional[str] = None) -> str:
        """
        Generate answer for query given context using the prompt structure from embeddings.py:
            Answer only using the context.
            Context: {context}
            Question: {query}
            Answer:
        """
        if context is None:
            docs = self.retrieve_context(query)
            context = "\n\n".join(d.page_content for d in docs)

        prompt = f"""Answer only using the context.

Context:
{context}

Question:
{query}

Answer:
"""
        # Try primary LLM first
        try:
            from llm_config import llm
            from langchain_core.messages import SystemMessage, HumanMessage
            resp = llm.invoke([
                SystemMessage(content="You are a helpful AI assistant. Answer strictly using only the provided context."),
                HumanMessage(content=prompt)
            ])
            if resp and resp.content:
                return resp.content.strip()
        except Exception as e:
            print(f"[INFO] LLM invoke failed or unconfigured ({e}), using generator.")

        # Fallback to pipeline generator
        if self.generator:
            try:
                res = self.generator(
                    prompt,
                    max_new_tokens=256,
                    truncation=True,
                    return_full_text=False
                )
                return res[0]["generated_text"].strip()
            except Exception as e:
                print(f"[ERROR] Generator failed: {e}")

        return f"Retrieved Context:\n\n{context}"

    def process_pasted_data(self, text: str, user_query: Optional[str] = None) -> Dict[str, Any]:
        """
        Main entry point for handling pasted data > 20 lines:
        1. Ingests text into FAISS embeddings
        2. Determines the best query (explicit query or extracted question/summary prompt)
        3. Retrieves relevant chunks via hybrid ensemble + reranker
        4. Generates an answer strictly using context
        """
        documents = self.ingest_pasted_text(text)

        query = user_query
        if not query or not query.strip():
            # Check if user formulated a question in the first or last few lines
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            for l in lines[:3] + lines[-3:]:
                if l.endswith("?") or any(l.lower().startswith(q) for q in ["what", "how", "why", "when", "who", "where", "summarize", "explain"]):
                    query = l
                    break
            if not query:
                query = "Summarize the key information, major points, and details provided in this text."

        retrieved_docs = self.retrieve_context(query)
        context = "\n\n".join(d.page_content for d in retrieved_docs)
        answer = self.answer_query(query, context=context)

        return {
            "answer": answer,
            "query": query,
            "chunk_count": len(documents),
            "retrieved_count": len(retrieved_docs),
            "retrieved_docs": retrieved_docs,
            "context": context
        }


# Global singleton instance
embedding_service = EmbeddingService()
