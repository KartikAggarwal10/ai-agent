"""
langraph_agent_fixed.py
=======================
Fixed version of langraph_agent.py  — original file is NOT modified.
All 17 bugs resolved (see implementation_plan.md for the full list).

Bug fixes summary:
  #1  TypedDict cannot have inline default values            → use Optional[bytes]
  #2  Task used before it was defined                        → moved above State
  #3  6 tools missing from codebase                         → all defined below
  #4  helper.main() called synchronously (it is async)      → asyncio.create_task()
  #5  with_structured_output() called twice on same LLM     → called once
  #6  state.question on TypedDict                           → state["question"]
  #7  need_img returned bare bool, not a state dict         → returns dict
  #8  no conditional edge for screenshot routing            → route_after_planner()
  #9  embedding loop used vector as index                   → enumerate() fix
  #10 raw PNG bytes decoded as UTF-8 (crashes)             → base64.b64encode() first
  #11 helper.send_message called with wrong args, not await → fixed call + await
  #12 state['result'][dep] could KeyError                   → .get() with fallback
  #13 TOOLS(tool.tool) — dict called as function            → TOOLS[tool.tool]
  #14 pending was a set; .values() / del called on it       → changed to dict
  #15 state missing from execute_tool call                  → passed explicitly
  #16 regular def tools awaited                             → all tools are async
  #17 asyncio.gather() not awaited                          → await added
  +   Graph wiring was completely absent                    → build_graph() added
"""

import asyncio
import base64
import os
from typing import Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
import numpy as np
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sentence_transformers import SentenceTransformer

from testting import helper as HelperClass


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

embedding_model = SentenceTransformer("./embedding_model")


def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


# ---------------------------------------------------------------------------
# Pydantic models
# Bug #2 fix: Task must be defined BEFORE State (State references Task)
# ---------------------------------------------------------------------------

class ToolStep(BaseModel):
    order: int = Field(description="Execution order of this tool.")
    tool: str = Field(description="Tool name.")
    params: dict = Field(
        default_factory=dict,
        description="Arguments for this tool.",
    )


class Task(BaseModel):
    task_id: str
    name: str
    depends_on: list[str] = Field(default_factory=list)
    tools: list[ToolStep]
    crnt_tool: int = 0


class PlannerOutput(BaseModel):
    need_screenshot: bool = Field(
        description="Whether a screenshot is required."
    )
    tasks: list[Task]


# ---------------------------------------------------------------------------
# State
# Bug #1 fix: TypedDict fields cannot have inline defaults (= None).
#             Mark the field as Optional[bytes] and handle None at runtime.
# Bug #2 fix: Task class is now defined above (see above).
# ---------------------------------------------------------------------------

class State(TypedDict):
    user_name: str
    email: str
    question: str
    screenshot_bytes: Optional[bytes]              # Bug #1 fix
    need_screenshot: bool                          # added for conditional routing
    previous_content_summary: list[str]
    previous_content_summary_embeddings: list[list[float]]
    result: dict                                   # {task_id: list[str]}
    previous_content_needed: list[str]
    tasks: list[Task]


# ---------------------------------------------------------------------------
# LLM
# Bug #5 fix: .with_structured_output() called only ONCE, stored in planner_llm
# ---------------------------------------------------------------------------

llm = ChatOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
    model="google/gemma-4-26b-a4b-it:free",
)

planner_llm = llm.with_structured_output(PlannerOutput)   # Bug #5 fix


# ---------------------------------------------------------------------------
# Tool implementations
# Bug #3 fix: all 7 tools that were referenced but never defined
# Bug #16 fix: every tool is async so they can be awaited in execute_tool
# ---------------------------------------------------------------------------

async def rag(state: State, prv: str, depended: list[str]) -> str:
    """
    Retrieval-Augmented Generation.
    Replace the body with your actual vector-store / RAG pipeline.
    """
    # TODO: query your vector store with state["question"]
    return f"[rag] stub — query: {state['question']}"


async def memory_search(state: State, prv: str, depended: list[str]) -> str:
    """
    Search past conversation memory.
    Replace the body with your memory backend (e.g. Redis, Chroma).
    """
    # TODO: implement memory / conversation history search
    return "[memory_search] stub — no memory backend connected yet."


async def browser_search(state: State, prv: str, depended: list[str]) -> str:
    """
    Web search.
    Wire Tavily / SerpAPI / Brave here.
    TAVILY_API_KEY is in .env.local.
    """
    # TODO: e.g. from langchain_community.tools.tavily_search import TavilySearchResults
    return f"[browser_search] stub — query: {state['question']}"


async def summarize(state: State, prv: str, depended: list[str]) -> str:
    """Summarise the output of the previous tool step."""
    text_to_summarize = prv or "\n".join(depended)
    if not text_to_summarize.strip():
        return "[summarize] nothing to summarize."

    messages = [
        SystemMessage(content="Summarize the following text concisely."),
        HumanMessage(content=text_to_summarize),
    ]
    res = llm.invoke(messages)
    return res.content


async def send_email(state: State, prv: str, depended: list[str]) -> str:
    """
    Send an email to the user.
    Replace the body with SMTP / SendGrid / etc.
    """
    recipient = state.get("email", "unknown")
    body = prv or "\n".join(depended)
    # TODO: implement real email dispatch
    print(f"[send_email] Would send to {recipient}:\n{body}")
    return f"[send_email] Email queued for {recipient}."


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
    res = llm.invoke(messages)
    return res.content


async def answer_tool(state: State, prv: str, depended: list[str]) -> str:
    """
    Final answer node — combines query, previous tool output, dependency
    outputs, and optional screenshot into a single LLM call.
    Bug #10 fix: base64-encode raw bytes before embedding in the message.
    Bug #6  fix: state["question"] not state.question
    """
    requery = (
        state["question"]                  # Bug #6 fix
        + "\n\n"
        + prv
        + "\n\n"
        + "\n".join(depended)
    )

    content: list[dict] = [{"type": "text", "text": requery}]

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
                "You are a helpful AI assistant. You will be provided with the "
                "user's current query, an optional screenshot, and summaries of "
                "relevant previous results of the same query. Also provided are "
                "relevant results of similar questions. "
                "Analyze all available information and help resolve the user's issue."
            )
        ),
        HumanMessage(content=content),
    ]
    res = llm.invoke(messages)
    return res.content


# ---------------------------------------------------------------------------
# TOOLS registry
# Bug #3 fix: all tools are now defined above so this dict is valid
# ---------------------------------------------------------------------------

TOOLS: dict[str, object] = {
    "rag": rag,
    "memory_search": memory_search,
    "browser_search": browser_search,
    "summarize": summarize,
    "send_email": send_email,                                        # previous content needed
    "answer": answer_tool,
    "ask_interview_questions_from_project_displaying": ask_interview_questions_from_project_displaying,
}


# ---------------------------------------------------------------------------
# WebSocket helper singleton
# Bug #4 fix: .main() is async — do NOT call it synchronously.
#             It is started as a background task inside run_agent() below.
# ---------------------------------------------------------------------------

ws_helper = HelperClass()


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def need_img(state: State) -> dict:
    """
    Planner node: uses the LLM to decompose the user's request into tasks
    and decides whether a screenshot is required.

    Bug #5 fix: planner_llm already has structured output; don't wrap again.
    Bug #6 fix: state["question"] not state.question.
    Bug #7 fix: return a state-update dict (not a bare bool).
    Bug #8 fix: screenshot routing is handled by a conditional edge below.
    """
    messages = [
        SystemMessage(
            content="""\
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
- ask_interview_questions_from_project_displaying

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
        HumanMessage(content=state["question"]),    # Bug #6 fix
    ]

    plan: PlannerOutput = planner_llm.invoke(messages)

    return {
        "tasks": plan.tasks,
        "need_screenshot": plan.need_screenshot,    # Bug #7 fix: return dict
        "result": {},                               # initialise result bucket
    }


async def get_img(state: State) -> dict:
    """Capture a fresh screenshot from the connected browser tab."""
    ws_helper.latest_screenshot = None
    await ws_helper.request_screenshot()

    while ws_helper.latest_screenshot is None:
        await asyncio.sleep(0.1)

    print("Screenshot received")
    return {"screenshot_bytes": ws_helper.latest_screenshot}


def check_which_previous_content_is_needed(state: State) -> dict:
    """
    Semantic similarity search over previous conversation summaries.
    Bug #9 fix: the original used 'for i in embeddings' making i the vector
                itself, then used it as an index — fixed with enumerate().
    """
    query_embedding = embedding_model.encode([state["question"]])[0]    # Bug #9 fix
    result: list[str] = []

    summaries = state.get("previous_content_summary", [])
    embeddings = state.get("previous_content_summary_embeddings", [])

    for idx, emb in enumerate(embeddings):          # Bug #9 fix: enumerate
        score = cosine_similarity(query_embedding, emb)
        if score > 0.75:
            result.append(summaries[idx])           # Bug #9 fix: index by position

    return {"previous_content_needed": result}


async def give_output_to_user(state: State) -> dict:
    """
    Push final results back to the connected browser over WebSocket.
    Bug #11 fix: send_message is async → must be awaited.
    Bug #11 fix: send_message takes (message_type, data), not just data=.
    """
    await ws_helper.send_message("result", state["result"])    # Bug #11 fix
    return {}


# ---------------------------------------------------------------------------
# Task / tool execution engine
# ---------------------------------------------------------------------------

async def execute_tool(
    tool: ToolStep,
    prv: str,
    depend_result: list[str],
    state: State,                       # Bug #15 fix: state was missing from signature
) -> str:
    """
    Look up the tool function and call it.
    Bug #13 fix: TOOLS[tool.tool]  not  TOOLS(tool.tool)  (dict, not callable)
    Bug #16 fix: all tool functions are async, so we can safely await them
    """
    tool_fn = TOOLS[tool.tool]          # Bug #13 fix: subscript, not call
    result = await tool_fn(             # Bug #16 fix: tools are async
        state=state,
        prv=prv,
        depended=depend_result,
    )
    return result


async def execute_task(tsk: Task, state: State) -> None:
    """Execute a single task's tool chain sequentially."""
    state["result"].setdefault(tsk.task_id, [])
    prev_output = ""

    for tool in sorted(tsk.tools, key=lambda t: t.order):
        # Bug #12 fix: use .get() so missing dependency keys don't crash
        dep_outputs = [
            state["result"].get(dep_id, [""])[-1]
            for dep_id in tsk.depends_on
        ]
        prev_output = await execute_tool(
            tool, prev_output, dep_outputs, state   # Bug #15 fix: pass state
        )
        state["result"][tsk.task_id].append(prev_output)


async def executor(state: State) -> dict:
    """
    Execute all tasks respecting depends_on; ready tasks run in parallel.

    Bug #14 fix: pending was a set — sets have no .values() and no key delete.
                 Changed to a dict {task_id: Task}.
    Bug #17 fix: asyncio.gather() was not awaited — tasks were fire-and-forget.
    """
    # Bug #14 fix: dict instead of set
    pending: dict[str, Task] = {tsk.task_id: tsk for tsk in state["tasks"]}
    completed: set[str] = set()

    while pending:
        ready = [
            task
            for task in pending.values()                # Bug #14 fix: .values() on dict
            if all(dep in completed for dep in task.depends_on)
        ]

        if not ready:
            raise RuntimeError(
                "Dependency deadlock: no tasks are runnable but pending is "
                "non-empty. Check the depends_on relationships in your tasks."
            )

        await asyncio.gather(                           # Bug #17 fix: awaited
            *(execute_task(tsk, state) for tsk in ready)
        )

        for task in ready:
            completed.add(task.task_id)
            del pending[task.task_id]                   # Bug #14 fix: del from dict

    return {"result": state["result"]}


# ---------------------------------------------------------------------------
# Conditional edge router
# Bug #8 fix: need_img used to return a bool — routing is now done here
# ---------------------------------------------------------------------------

def route_after_planner(state: State) -> str:
    """Return the name of the next node based on whether a screenshot is needed."""
    if state.get("need_screenshot"):
        return "get_img"
    return "check_which_previous_content_is_needed"


# ---------------------------------------------------------------------------
# Build and compile the LangGraph graph
# (This section was completely missing in the original file)
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(State)

    # ── Nodes ────────────────────────────────────────────────────────────────
    graph.add_node("need_img",                             need_img)
    graph.add_node("get_img",                              get_img)
    graph.add_node("check_which_previous_content_is_needed",
                   check_which_previous_content_is_needed)
    graph.add_node("executor",                             executor)
    graph.add_node("give_output_to_user",                  give_output_to_user)

    # ── Edges ─────────────────────────────────────────────────────────────────
    graph.add_edge(START, "need_img")

    # Bug #8 fix: conditional edge routes based on need_screenshot flag
    graph.add_conditional_edges(
        "need_img",
        route_after_planner,
        {
            "get_img": "get_img",
            "check_which_previous_content_is_needed": "check_which_previous_content_is_needed",
        },
    )

    # After screenshot → memory check
    graph.add_edge("get_img", "check_which_previous_content_is_needed")

    # Memory check → task execution
    graph.add_edge("check_which_previous_content_is_needed", "executor")

    # Execution → send output
    graph.add_edge("executor", "give_output_to_user")

    graph.add_edge("give_output_to_user", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_agent(initial_state: State):
    """
    Start the WebSocket server as a background task (Bug #4 fix), then
    compile and invoke the LangGraph agent.
    """
    # Bug #4 fix: helper.main() is async and runs an infinite WebSocket server.
    #             Must be a background task, NOT called synchronously.
    asyncio.create_task(ws_helper.main())
    app = build_graph()
    result = await app.ainvoke(initial_state)
    return result


# ---------------------------------------------------------------------------
# Quick smoke-test entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_state: State = {
        "user_name": "Alice",
        "email": "alice@example.com",
        "question": "Search the web for the latest Python news and summarize it.",
        "screenshot_bytes": None,
        "need_screenshot": False,
        "previous_content_summary": [],
        "previous_content_summary_embeddings": [],
        "result": {},
        "previous_content_needed": [],
        "tasks": [],
    }
    asyncio.run(run_agent(sample_state))
