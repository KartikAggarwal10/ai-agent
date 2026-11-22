# from pypdf import PdfReader

# reder = PdfReader("")

# text = " "

# for i in reder.pages:
#     text += i.extract_text() +"\n"

# chunk_sise = 500

# chunks = [
#     text[i,i+chunk_sise]
#     for i in range(0,len[text],chunk_sise-20)
# ]
# from langchain_community.document_loaders import PyPDFLoader
# from langchain_text_splitters import RecursiveCharacterTextSplitter
# from transformers import AutoModel, AutoTokenizer
# from langchain_community.vectorstores import FAISS
# from langchain_huggingface import HuggingFaceEmbeddings
# loader = PyPDFLoader("creating_own_livekit\\python_part\\AcmeCloud_Solutions_Fictional_Company_Brochure.pdf")

# docs = loader.load()

# splitter = RecursiveCharacterTextSplitter(
#     chunk_size=500,
#     chunk_overlap=100
# )

# documents = splitter.split_documents(docs)

# embedding = AutoTokenizer.from_pretrained("embedding_model")
# embedding = HuggingFaceEmbeddings(
#     model_name="./embedding_model"
# )

# db = FAISS.from_documents(
#     documents,
#     embedding
# )

# db.save_local("vectorstore")

# print("Vector DB Created")


from langchain_huggingface import HuggingFaceEmbeddings

from langchain_community.vectorstores import FAISS

from langchain_community.retrievers import BM25Retriever

from langchain_classic.retrievers import EnsembleRetriever

from langchain_classic.retrievers.document_compressors import CrossEncoderReranker

from langchain_community.cross_encoders import HuggingFaceCrossEncoder

from langchain_classic.retrievers import ContextualCompressionRetriever

from transformers import pipeline

# -------------------
# Embeddings
# -------------------

embedding = AutoTokenizer.from_pretrained("embedding_model")
embedding = HuggingFaceEmbeddings(
    model_name="./embedding_model"
)

# -------------------
# Vector DB
# -------------------

db = FAISS.load_local(
    "vectorstore",
    embedding,
    allow_dangerous_deserialization=True
)

vector_retriever = db.as_retriever(
    search_kwargs={
        "k":20
    }
)

# -------------------
# BM25
# -------------------

docs = db.similarity_search("",k=1000)

bm25 = BM25Retriever.from_documents(docs)

bm25.k = 20

# -------------------
# Hybrid Retrieval
# -------------------

ensemble = EnsembleRetriever(
    retrievers=[
        vector_retriever,
        bm25
    ],
    weights=[0.5,0.5]
)

# -------------------
# Reranker
# -------------------

model = HuggingFaceCrossEncoder(
    model_name="BAAI/bge-reranker-base"
)

reranker = CrossEncoderReranker(
    model=model,
    top_n=5
)

compression = ContextualCompressionRetriever(
    base_retriever=ensemble,
    base_compressor=reranker
)

# -------------------
# Generator
# -------------------

generator = pipeline(
    "text2text-generation",
    model="google/flan-t5-large"
)

# -------------------
# Chat
# -------------------

while True:

    question = input("\nYou : ")

    if question.lower()=="exit":
        break

    docs = compression.invoke(question)

    context = "\n\n".join(
        d.page_content
        for d in docs
    )

    prompt = f"""
Answer only using the context.

Context:
{context}

Question:
{question}

Answer:
"""

    answer = generator(
        prompt,
        max_new_tokens=256
    )[0]["generated_text"]

    print("\nAssistant:\n")
    print(answer)         




