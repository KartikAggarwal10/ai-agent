from typing import TypedDict
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
import base64
from langgraph.types import interrupt
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from tavily import AsyncTavilyClient
from pymongo import MongoClient
from langchain_core.messages import HumanMessage, SystemMessage
import asyncio
from testting import helper
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
import numpy as np
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_classic.retrievers import ContextualCompressionRetriever
from transformers import pipeline
from langchain_huggingface import HuggingFaceEmbeddings
from transformers import AutoTokenizer,AutoModelForSeq2SeqLM
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from pathlib import Path
import asyncio
from dotenv import load_dotenv
import contextlib
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
import functools
from llm_config import llm, vision_llm
from human_in_the_loop import (
    hitl_login_wrapper,
    hitl_confirm_create_order,
    hitl_confirm_create_product,
    hitl_create_post_wrapper,
    hitl_accept_follow_wrapper,
    hitl_send_email_wrapper
)
import json
load_dotenv()

# Parameters to run your servers
posts_server_params = StdioServerParameters(command="python", args=["mcp_servers/posts_server/server.py"])
ecommerce_params = StdioServerParameters(command="python", args=["mcp_servers/ecommerce/server.py"])
tavily = AsyncTavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# -------------------
# Embeddings & Hybrid Retrieval Service (Shared with testting.py)
# -------------------
from embedding_service import (
    embedding_service,
    is_more_than_20_lines,
    EMBEDDING_MODEL_PATH
)

embedding = embedding_service.embedding
db = embedding_service.db
vector_retriever = embedding_service.vector_retriever
bm25 = embedding_service.bm25
ensemble = embedding_service.ensemble
reranker = embedding_service.reranker
compression = embedding_service.compression
generator = embedding_service.generator

def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

model = SentenceTransformer(EMBEDDING_MODEL_PATH)

# -------------------
# MongoDB Memory
# -------------------
try:
    mongo_client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    mongo_db = mongo_client["live_kit"]
    memory_collection = mongo_db["conversations"]
except Exception as e:
    print(f"[WARNING] MongoDB connection failed: {e}")
    mongo_client = None
    mongo_db = None
    memory_collection = None

class ToolStep(BaseModel):
    order: int = Field(description="Execution order of this tool.")
    tool: str = Field(description="Tool name.")
    params: dict = Field(
        default_factory=dict,
        description="Arguments for this tool."
    )
    instruction: str = Field(
        default="",
        description=(
            "Natural language instruction describing what specific information "
            "this tool needs to extract and use from the outputs of the "
            "preceding tool or dependency tasks."
        ),
    )
class Task(BaseModel):
    task_id: str
    name: str
    depends_on: list[str] = Field(default_factory=list)
    tools: list[ToolStep]
    crnt_tool : int = 0

class PlannerOutput(BaseModel):
    thought: str = Field(
        description="Step-by-step reasoning explaining the user's intent and why each tool was chosen."
    )
    need_screenshot: bool = Field(
        description="Whether a screenshot is required."
    )
    tasks: list[Task]

class State(TypedDict):
    user_name:str
    email:str
    question : str
    screenshot_bytes: bytes | None 
    result:dict[str, list[str]]
    previous_content_needed: list[str]
    tasks : list[Task]
    need_img : bool
    completed_tasks : list[str]
    social_media_user_name : str
    social_media_password : str
    ecommerce_user_name : str
    ecommerce_password : str



# llm = ChatOpenAI(
#     api_key=os.getenv("OPENROUTER_API_KEY"),
#     base_url="https://openrouter.ai/api/v1",
#     model="google/gemma-4-26b-a4b-it:free",
# )

async def ask_interview_questions_from_project_displaying(
    state: State, prv: str, depended: list[str]
) -> str:
    """Generate interview questions based on what is visible on screen."""
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "The user is working on a project. "
                "Generate relevant technical interview questions.\n\n"
                f"Context: {prv}\n\n {"\n".join(depended)}"
                f"Question: {state['question']}"
            ),
        }
    ]

    # Bug #10 fix: raw bytes → base64 string before putting in the JSON payload
    if state.get("screenshot_bytes") is not None:
        image_b64 = base64.b64encode(state["screenshot_bytes"]).decode("utf-8")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            }
        )

    messages = [
        SystemMessage(content="You are an expert technical interviewer."),
        HumanMessage(content=content),
    ]
    res = vision_llm.invoke(messages)
    return res.content

async def rag(state: State, prv: str, depended: list[str]) -> str:
    """RAG tool powered by embedding_service (FAISS + BM25 + CrossEncoder reranker)."""
    docs = embedding_service.retrieve_context(prv)
    context = "\n\n".join(
        d.page_content
        for d in docs
    )
    return embedding_service.answer_query(prv, context=context)
async def send_email(
    to_email: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None
) -> str:
    print("========== SEND EMAIL CALLED ==========", flush=True)
    try:
        smtp_server = "smtp.gmail.com"
        smtp_port = 587

        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")
        print(gmail_user + " -- " + to_email + " -- " + gmail_password)
        if not gmail_user or not gmail_password:
            return "credentials not configured"

        msg = MIMEMultipart()
        msg["From"] = gmail_user
        msg["To"] = to_email
        msg["Subject"] = subject

        recipients = [to_email]

        if cc_email:
            msg["Cc"] = cc_email
            recipients.append(cc_email)

        msg.attach(MIMEText(message, "plain"))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        print("logging in")
        server.login(gmail_user, gmail_password)
        print("lets send")
        server.sendmail(
            gmail_user,
            recipients,
            msg.as_string()
        )
        print("done")
        server.quit()

        return f"Email successfully sent to {to_email}"

    except smtplib.SMTPAuthenticationError:
        return "email sending failed: authentication failed. Check credentials"

    except smtplib.SMTPException:
        return "email sending failed: SMTP error"

    except Exception as e:
        return f"email sending failed: {str(e)}"
async def answer_tool(state: State, prv: str, depended: list[str]) -> str:
    """
    Final answer node — takes prv as input and also the image and gives to llm to answer questions
    """
    content: list[dict] = [{"type": "text", "text": f"Question: {state['question']}\n\nContext:\n{prv}"}]

    # Bug #10 fix: encode raw PNG bytes to base64 string
    if state.get("screenshot_bytes") is not None:
        image_b64 = base64.b64encode(state["screenshot_bytes"]).decode("utf-8")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            }
        )

    messages = [
        SystemMessage(
            content=(
                "You are a helpful AI assistant. "
                "Answer the user's question using the provided context."
            )
        ),
        HumanMessage(content=content),
    ]
    res = vision_llm.invoke(messages)
    return res.content
async def browser_search(state: State, prv: str, depended: list[str]):
    for attempt in range(3):
        try:
            response = await tavily.search(
                query=prv,
                max_results=1
            )

            return response["results"][0]["content"]

        except Exception as e:
            if attempt == 2:
                raise e

    return None
async def summarize(state: State, prv: str, depended: list[str]):
    content = [
        SystemMessage("you are a helpfull ai summarizer. you will be given a query. just summarize it."),
        HumanMessage(content=f"query: {prv}")
    ]
    result = llm.invoke(content)
    return result.content

async def memory_search(state: State, prv: str, depended: list[str]) -> str:
    """
    Search past conversation memory from MongoDB (live_kit database).
    Finds the most semantically similar past messages for this user.
    """
    if memory_collection is None:
        return "Memory unavailable: MongoDB is not connected."
    user_name = state.get("user_name", "")
    query_text = prv or state.get("question", "")

    if not query_text:
        return "No query provided for memory search."

    # Fetch all past memories for this user
    past_docs = list(memory_collection.find(
        {"user_name": user_name},
        {"_id": 0, "message": 1, "response": 1}
    ))

    if not past_docs:
        return "No past memory found for this user."

    # Embed the query
    query_embedding = model.encode(query_text)

    # Score each memory by cosine similarity
    scored = []
    for doc in past_docs:
        doc["embedding"] = model.encode(doc.response)
        doc_embedding = np.array(doc["embedding"])
        score = cosine_similarity(query_embedding, doc_embedding)
        scored.append((score, doc))

    if not scored:
        return "No embeddings found in memory."

    # Sort by similarity descending, take top 3
    scored.sort(key=lambda x: x[0], reverse=True)
    top_memories = scored[:3]

    # Format result
    result_parts = []
    for rank, (score, doc) in enumerate(top_memories, 1):
        result_parts.append(
            f"[Memory {rank} | similarity: {score:.2f}]\n"
            f"User said: {doc.get('message', '')}\n"
            f"Assistant replied: {doc.get('response', '')}"
        )

    return "\n\n".join(result_parts)

TOOLS = {
    "rag": rag,
    "memory_search": memory_search,
    "browser_search": browser_search,
    "summarize": summarize,
    "send_email": functools.partial(hitl_send_email_wrapper, send_email), # previous content needed
    "answer": answer_tool,
}

mcp_sessions = {} 

def make_mcp_wrapper(session_name, tool_name):
    # 1. The original function that talks to the server
    async def base_wrapper(state: State, prv: str, depended: list[str], params: dict = None):
        if params is None:
            params = {}
        # Guard: if params arrived as a string (e.g. str(dict) from serde), parse it back
        if isinstance(params, str):
            import ast, json as _json
            try:
                params = _json.loads(params)
            except Exception:
                try:
                    params = ast.literal_eval(params)
                except Exception:
                    params = {}
        session = mcp_sessions.get(session_name)
        if not session:
            return f"Error: MCP session {session_name} not found"
        try:
            print("going to run " + str(type(params)) + str(params))
            res = await session.call_tool(tool_name, arguments=params)  # ← keyword arg fix
            
            return res.content[0].text if res.content else ""
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"Error calling {tool_name}: {str(e)}"
            
    # 2. The new HITL interceptor function
    async def final_wrapper(state: State, prv: str, depended: list[str], params: dict = None):
        if tool_name in ["login", "login_posts", "login_ecommerce"]:
            return await hitl_login_wrapper(base_wrapper, state, prv, depended, params)
            
        elif tool_name == "create_post":
            return await hitl_create_post_wrapper(base_wrapper, state, prv, depended, params)
            
        elif tool_name == "accept_follow_request":
            return await hitl_accept_follow_wrapper(base_wrapper, state, prv, depended, params)
            # in ["create_order", "update_order_status", "create_product"]:
        elif tool_name == "create_order":
            return await hitl_confirm_create_order(base_wrapper, tool_name, state, prv, depended, params)
        elif tool_name == "create_product":
            return await hitl_confirm_create_product(base_wrapper, tool_name, state, prv, depended, params)
        else:
            # For all other tools, just run normally without interrupting
            return await base_wrapper(state, prv, depended, params)
            
    final_wrapper.is_mcp = True
    return final_wrapper


TOOLS["create_post"] = make_mcp_wrapper("posts", "create_post")
TOOLS["get_posts"] = make_mcp_wrapper("posts", "get_posts")
TOOLS["get_post"] = make_mcp_wrapper("posts", "get_post")
TOOLS["login_posts"] = make_mcp_wrapper("posts", "login")
TOOLS["get_user_requests"] = make_mcp_wrapper("posts", "get_user_requests")
TOOLS["accept_follow_request"] = make_mcp_wrapper("posts", "accept_follow_request")

TOOLS["get_products"] = make_mcp_wrapper("ecommerce", "get_products")
TOOLS["get_product"] = make_mcp_wrapper("ecommerce", "get_product")
TOOLS["create_order"] = make_mcp_wrapper("ecommerce", "create_order")
TOOLS["get_order"] = make_mcp_wrapper("ecommerce", "get_order")
TOOLS["get_user_orders"] = make_mcp_wrapper("ecommerce", "get_user_orders")
TOOLS["update_order_status"] = make_mcp_wrapper("ecommerce", "update_order_status")
TOOLS["create_product"] = make_mcp_wrapper("ecommerce", "create_product")
TOOLS["login_ecommerce"] = make_mcp_wrapper("ecommerce", "login")

helper =  helper()

async def run_with_mcp():
    async with contextlib.AsyncExitStack() as stack:
        try:
            # Start posts server
            posts_params = StdioServerParameters(command="python", args=["mcp_servers/posts_server/server.py"])
            posts_read, posts_write = await stack.enter_async_context(stdio_client(posts_params))
            posts_session = await stack.enter_async_context(ClientSession(posts_read, posts_write))
            await posts_session.initialize()
            mcp_sessions["posts"] = posts_session
            
            # Start ecommerce server
            ecomm_params = StdioServerParameters(command="python", args=["mcp_servers/ecommerce_server/server.py"])
            ecomm_read, ecomm_write = await stack.enter_async_context(stdio_client(ecomm_params))
            ecomm_session = await stack.enter_async_context(ClientSession(ecomm_read, ecomm_write))
            await ecomm_session.initialize()
            mcp_sessions["ecommerce"] = ecomm_session
            
            print("[INFO] MCP Servers initialized successfully.")
        except Exception as e:
            print(f"[WARNING] Failed to initialize MCP servers: {e}")
            
        await helper.main()
# langraph_agent.py, replacing line 487
if __name__ == "__main__":
    asyncio.run(run_with_mcp())


use_img_or_not = llm.with_structured_output(PlannerOutput, method="function_calling")

async def extract_inputs_from_outputs(instruction: str, context: str, has_prior_data: bool) -> str:
    """
    - has_prior_data=False: nothing has run yet, so there's nothing to "extract".
      Formulate the tool's input (e.g. a search query) from the question + instruction.
    - has_prior_data=True: real upstream output exists, so extract/synthesize
      from it per the instruction.
    """
    if not instruction.strip():
        return context

    if not has_prior_data:
        system_prompt = (
            "You are a tool-input formulator. You're given the user's original "
            "question and an instruction describing what a tool needs as input "
            "(e.g. a search query). There is no prior tool output to check — that's "
            "expected, not missing data. Produce ONLY the input value itself: no "
            "explanations, no preamble, no quotes, no commentary on data availability."
        )
    else:
        system_prompt = (
            "You are an information extraction assistant. Given context containing "
            "prior tool outputs and an instruction, extract or synthesize only the "
            "specific information requested. Return only the extracted content — "
            "no preamble, no commentary about whether it was found."
        )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Context:\n{context}\n\nInstruction: {instruction}\n\nOutput:"),
    ]
    res = await llm.ainvoke(messages)
    return res.content.strip()


def generate_plan_readme(question: str, plan: PlannerOutput) -> str:
    """Helper to format the tasks and thought into a clean Markdown README."""
    lines = [
        f"# Execution Specification & Plan",
        f"**User Request:** {question}\n",
        f"## 🧠 Strategy & Thought Process",
        f"{plan.thought}\n",
        f"## 📋 Planned Tasks & Tool Execution Sequence",
    ]
    for idx, task in enumerate(plan.tasks, 1):
        deps = f" *(Depends on: {', '.join(task.depends_on)})*" if task.depends_on else ""
        lines.append(f"### Task {idx}: {task.name}{deps}")
        for step in task.tools:
            param_str = f" with `{step.params}`" if step.params else ""
            instruction = f" — *{step.instruction}*" if step.instruction else ""
            lines.append(f"- **Step {step.order}**: `{step.tool}`{param_str}{instruction}")
        lines.append("")

    lines.append(f"**Screen Capture Needed:** {'Yes 📸' if plan.need_screenshot else 'No ❌'}")
    return "\n".join(lines)


async def need_img(state: State):
    if is_more_than_20_lines(state.get("question", "")):
        print("[INFO] Question has >20 lines. Ingesting into embeddings...")
        embedding_service.ingest_pasted_text(state["question"])

    planner = use_img_or_not

    messages = [
        SystemMessage(
                    content="""
                You are an AI task planner.

            Your responsibilities are:

        1. Decide whether the user's screen is required.
        2. Break the user's request into high-level executable tasks.
        3. Decide which tools are needed for each task.
        4. Return the tasks.

        Available tools:
        - rag
        - memory_search
        - browser_search
        - send_email
        - summarize
        - answer
        
        # Posts Server Tools:
        - create_post (params: title, content, category, cover)
        - get_posts (params: limit, offset, category, author)
        - get_post (params: post_id)
        - login_posts (params: email, password)
        - get_user_requests
        - accept_follow_request (params: userId)
        
        # Ecommerce Server Tools:
        - get_products (params: limit, category, search, min_price, max_price, in_stock_only)
        - get_product (params: product_id)
        - create_order (params: user_id, items, shipping_address, payment_method)
        - get_order (params: order_id, user_id)
        - get_user_orders (params: user_id, limit, offset, status)
        - update_order_status (params: user_id, order_id, status)
        - create_product (params: name, description, price, category, stock, images)
        - login_ecommerce (params: email, password)

        Rules:

        - Use ONLY the available tool names.
        - A task represents one user goal.
        - A task may require multiple tools executed sequentially.
        - Different user goals should become different tasks.
        - Tasks that are independent should be able to run in parallel.
        - Only combine tools into the same task when they contribute to the SAME user goal.
        - Do not invent tool names.
        - Return only the structured output.
        - If Task B depends on Task A, then Task A must have a smaller execution order than Task B.
        - For each tool in a task, provide an `instruction` field: a concise natural
            language sentence describing what specific information that tool should
            extract from the outputs of the previous tool or dependency task outputs.
            Example: "Extract the main article body text from the browser_search output."
            If the tool is first in the chain and has no prior output, leave `instruction` empty.

        Examples

        Example 1

        User:
        "Summarize this article and email it to me."

        Output:

        Task:
        Name: Email article summary
        Tools:
        1. summarize
        2. send_email

        Reason:
        The summary is only an intermediate step needed to complete the email.

        ------------------------------------------------

        Example 2

        User:
        "Summarize this article. Also email me my transaction history."

        Output:

        Task 1
        Name: Summarize article
        Tools:
        1. summarize

        Task 2
        Name: Email transaction history
        Tools:
        1. send_email

        Reason:
        These are two independent user goals and can execute in parallel.

        ------------------------------------------------

        Example 3

        User:
        "Search the web for OpenAI news and summarize it."

        Output:

        Task:
        Name: Summarize OpenAI news
        Tools:
        1. browser_search
        2. summarize

        Reason:
        Searching is required before summarization, so both belong to one task.

        ------------------------------------------------

        Example 4

        User:
        "Search the web for OpenAI news and email my resume."

        Output:

        Task 1
        Name: Search OpenAI news
        Tools:
        1. browser_search

        Task 2
        Name: Email resume
        Tools:
        1. send_email

        Reason:
        The two goals are unrelated and should execute independently.

        ------------------------------------------------

        Example 5

        User:
        "Remember this conversation and answer my question."

        Output:

        Task 1
        Name: Search memory
        Tools:
        1. memory_search

        Task 2
        Name: Answer question
        Tools:
        1. answer

        Reason:
        The answer depends on the memory search, so Task 2 depends on Task 1.
        """
        ),
        HumanMessage(content=state["question"])
    ]
    current_plan = None
    retries = 3
    while current_plan is None and retries > 0:
        try:
            current_plan = await planner.ainvoke(messages)
        except Exception as e:
            print(f"Error invoking planner: {e}")
        retries -= 1
    if current_plan is None:
        return {"tasks": [], "need_img": False}
    # ─────────────────────────────────────────────────────────────────
    # HUMAN-IN-THE-LOOP: PLAN & README VERIFICATION
    # ─────────────────────────────────────────────────────────────────
    while True:
        # Generate the Markdown spec
        readme_markdown = generate_plan_readme(state["question"], current_plan)
        # Pause the graph and send plan details to frontend
        user_response = interrupt({
            "action": "verify_plan_readme",
            "message": "Please review the execution plan / README before proceeding.",
            "readme_markdown": readme_markdown,
            "tasks": [t.dict() for t in current_plan.tasks],
            "need_screenshot": current_plan.need_screenshot,
        })
        # If user approved the plan, break the loop and continue to execution
        if user_response.get("approved", False):
            print("[INFO] User approved the plan! Proceeding to execution.")
            break
        # If user suggested changes / gave feedback:
        user_feedback = user_response.get("feedback", "")
        print(f"[INFO] User requested changes to plan: {user_feedback}")
        # Ask LLM to revise the plan based on user feedback
        revision_messages = messages + [
            HumanMessage(
                content=(
                    f"Previous Plan:\n{readme_markdown}\n\n"
                    f"The user reviewed this plan and gave this feedback/changes: '{user_feedback}'.\n"
                    f"Please regenerate an updated plan addressing this feedback."
                )
            )
        ]
        try:
            current_plan = await planner.ainvoke(revision_messages)
        except Exception as e:
            print(f"Error regenerating plan: {e}")
    # Notify frontend of final tasks
    await give_tasks_created_to_user(current_plan.tasks)
    return {
        "tasks": current_plan.tasks,
        "need_img": current_plan.need_screenshot
    }



def route_after_need_image(state: State) -> str:
    return "get_image" if state["need_img"] else "executor"

async def get_img(state: State):
    helper.latest_screenshot = None

    await helper.request_screenshot()

    while helper.latest_screenshot is None:
        await asyncio.sleep(0.1)

    print("Screenshot received")

    return {
        "screenshot_bytes": helper.latest_screenshot
    }


async def give_output_to_user(state: State, task):
    data = task.name + str(state['result'][task.task_id][-1])
    await helper.send_message(message_type = 'result',data=data)


async def give_tasks_created_to_user(task):
    lines = []
    for task in task:
        lines.append(task.name + "\n" + ",".join(tool.tool for tool in task.tools))
    data = "\n".join(lines)
    await helper.send_message(message_type = 'procedure',data=data)
 
# async def execute_task(tsk : Task,state : State):
#     # Resume-safe: keep already-computed results, start from where we left off
#     results = state['result'].setdefault(tsk.task_id, [])

#     to_send = [state['result'][x][-1] for x in tsk.depends_on if state['result'].get(x)]

#     for idx in range(len(results), len(tsk.tools)):
#         tool = tsk.tools[idx]
#         prv = results[-1] if results else ""
#         result = await execute_tool(tool, prv, to_send, state)
#         results.append(result)
#         state.setdefault("completed_tasks", []).append(f"{tsk.task_id}:{idx}")

  #  await give_output_to_user(state,tsk)

async def execute_tool(tool: ToolStep, prv: str, depend_dtte_result: list[str], state: State):
    parts = []

    if state.get("question"):
        parts.append(f"Original User Question: {state['question']}")

    if depend_dtte_result:
        parts.append("Outputs from dependent tasks:\n" + "\n\n".join(depend_dtte_result))

    if prv:
        parts.append(f"Output from previous tool in this chain:\n{prv}")

    if tool.params:
        parts.append(f"Tool Parameters: {tool.params}")

    full_context = "\n\n---\n\n".join(parts)
    has_prior_data = bool(prv) or bool(depend_dtte_result)

    extracted = (
        await extract_inputs_from_outputs(tool.instruction, full_context, has_prior_data)
        if tool.instruction
        else full_context
    )

    print(f"prv for {tool.tool} (had_prior_data={has_prior_data}) = {extracted}")
    tool_nm = TOOLS[tool.tool]
    # Execute the tool
    if getattr(tool_nm, "is_mcp", False):
        result = await tool_nm(
            state=state,
            prv=extracted,
            depended=depend_dtte_result,
            params=tool.params
        )
    else:
        result = await tool_nm(
            state=state,
            prv=extracted,
            depended=depend_dtte_result
        )

    return result


async def executor(state: State):
    completed = set(state.get("completed_tasks", []))
    pending = {
        task.task_id: task
        for task in state["tasks"]
        if len(state['result'].get(task.task_id, [])) < len(task.tools)
    }

    if not pending:
        return state

    ready = [
        task
        for task in pending.values()
        if all(dep in completed for dep in task.depends_on)
    ]

    if not ready:
        raise ValueError("No executable task found. Possible circular dependency.")

    # Execute exactly ONE tool step from the first ready task
    task = ready[0]
    
    if "result" not in state:
        state["result"] = {}
    results = state['result'].setdefault(task.task_id, [])
    
    to_send = [state['result'][x][-1] for x in task.depends_on if state['result'].get(x)]

    idx = len(results)
    tool = task.tools[idx]
    prv = results[-1] if results else ""
    
    # Run the tool
    result = await execute_tool(tool, prv, to_send, state)
    results.append(result)
    
    # If this was the last tool in the task, mark the task as complete
    if len(results) == len(task.tools):
        completed.add(task.task_id)
        state["completed_tasks"] = list(completed)
        await give_output_to_user(state, task)
        
    # Crucial step: Return Command to immediately persist the state and loop back
    from langgraph.types import Command
    return Command(update=state, goto="executor")



from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

# Fix the langgraph msgpack warning/error for custom classes
serializer = JsonPlusSerializer(
    allowed_msgpack_modules=[
        ("langraph_agent", "Task"),
        ("langraph_agent", "ToolStep"),
        ("__main__", "Task"),
        ("__main__", "ToolStep"),
    ]
)
memory = MemorySaver(serde=serializer)



def builder():
    graph = StateGraph(State)
    graph.add_node("need_image", need_img)
    graph.add_node("get_image", get_img)
    graph.add_node("executor", executor)
    graph.add_edge(START,"need_image")
    graph.add_conditional_edges(
        "need_image",
        route_after_need_image,
        {
            "get_image": "get_image",
            "executor": "executor",
        },
    )

    graph.add_edge("get_image", "executor")
    graph.add_edge("executor", END)
    return graph.compile(checkpointer=memory)
