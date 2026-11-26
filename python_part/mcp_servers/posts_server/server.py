"""
MCP Server for Posts Website
Exposes posts API as MCP tools for the agent
"""
import os
import json
import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from pydantic import BaseModel
import httpx


# Configuration - UPDATE THESE WITH YOUR ACTUAL API ENDPOINTS
POSTS_API_BASE = os.getenv("POSTS_API_BASE", "http://localhost:3000/api/")
POSTS_API_KEY = os.getenv("POSTS_API_KEY", "your-api-key")

from typing import Optional, Dict, Any

# In-memory session state.
# Safe here because this is a stdio server: one process per client connection.
_session: Dict[str, Any] = {
    "user_id": None,
    "token": None,
    "email":None,
    "password" : None  # if your API returns an auth token on login, store that too
}
def require_user_id() -> str:
    """Fetch the logged-in user_id, or set a default user."""
    if not _session.get("user_id"):
        _session["user_id"] = "6a9ef1484aef827f7d43a9f1"
        _session["email"] = "aggarwalkartik956@gmail.com"
        _session["password"] = ""

    return _session["user_id"]
class CreatePostParams(BaseModel):
    title: str
    content: str
    author: Optional[str] = None
    tags: Optional[List[str]] = None
    category: str
    cover: str = "https://cdn2.fptshop.com.vn/unsafe/1920x0/filters:format(webp):quality(75)/2024_5_23_638520607014033063_postimage.jpg"
    published: bool = True
    

class GetPostsParams(BaseModel):
    limit: int = 10
    offset: int = 0
    category: Optional[str] = None
    author: Optional[str] = None


class UpdatePostParams(BaseModel):
    post_id: str
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    published: Optional[bool] = None


class DeletePostParams(BaseModel):
    post_id: str


class GetPostParams(BaseModel):
    post_id: str

class loginUserParams(BaseModel):
    email : str
    password : str
class accept_follow_request_tool(BaseModel):
    userId : str
async def make_api_request(method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
    """Make HTTP request to posts API"""
    headers = {
        "Authorization": f"Bearer {POSTS_API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{POSTS_API_BASE}{endpoint}"
        response = await client.request(method, url, headers=headers, json=data, params=params)
        response.raise_for_status()
        return response.json()



server = Server("posts-mcp-server")

##  no. of (requests came,followers,followed),see post,see user
@server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="create_post",
            description="Create a new post on the posts website",
            inputSchema=CreatePostParams.model_json_schema(),
        ),
        Tool(
            name="get_posts",
            description="Get list of posts with optional filters",
            inputSchema=GetPostsParams.model_json_schema(),
        ),
        Tool(
            name="get_post",
            description="Get a single post by ID",
            inputSchema=GetPostParams.model_json_schema(),
        ),
        Tool(
            name="login",
            description="login user",
            inputSchema=loginUserParams.model_json_schema(),
        ),
        Tool(
            name="get_user_requests",
            description="give accounts who have followed the user",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="accept_follow_request",
            description="give accounts who have followed the user",
            inputSchema = accept_follow_request_tool.model_json_schema()
        ),
    ]
@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        if name == "create_post":
            print("came in create post")
            user_id = require_user_id()
            if not user_id:
                return [TextContent(type="text", text="Error: Not logged in. Please call the 'login' tool first with your email and password.")]
            params = CreatePostParams(**arguments)
            data = params.model_dump(exclude_none=True)
            print("came in create post2" + str(data))
            data["user_id"] = user_id
            result = await make_api_request("POST", "create_post_mcp", data=data)
            print("came in create post3" + json.dumps(result, indent=2))
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_posts":
            params = GetPostsParams(**arguments)
            query_params = params.model_dump(exclude_none=True)
            result = await make_api_request("GET", "get_posts_mcp", params=query_params)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_post":
            params = GetPostParams(**arguments)
            user_id = require_user_id()
            if not user_id:
                return [TextContent(type="text", text="Error: Not logged in. Please call the 'login' tool first with your email and password.")]     
            email = _session.get("email")
            password = _session.get("password")
            
            if not email or password is None:
                return [TextContent(type="text", text="Error: You must call the 'login' tool first to set email and password for Playwright.")]

            print(" -- > == " + email + password + params.post_id)
            
            js_script_path = r"D:\ml_projects_from videos\creating_own_livekit\frontend\src\playwright\seepost.js"
            
            try:
                # Run the node script asynchronously
                cwd = r"D:\ml_projects_from videos\creating_own_livekit\frontend"
                process = await asyncio.create_subprocess_exec(
                    "node", js_script_path, email, password, params.post_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd
                )
                stdout, stderr = await process.communicate()
                
                output = stdout.decode()
                if stderr:
                    output += "\nErrors:\n" + stderr.decode()
                    
                return [TextContent(type="text", text=f"Playwright script executed:\n{output}")]
            except Exception as e:
                return [TextContent(type="text", text=f"Failed to run Playwright script: {str(e)}")]
        elif name == "login":
            params = loginUserParams(**arguments)
            result = await make_api_request("GET", f"login?email={params.email}&password={params.password}")
            if result.get("success") == True:
                _session["user_id"] = result.get("id")
                _session["email"] = params.email
                _session["password"] = params.password
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "get_user_requests":
            user_id = require_user_id()
            if not user_id:
                return [TextContent(type="text", text="Error: Not logged in. Please call the 'login' tool first with your email and password.")]
            result = await make_api_request("GET", f"get_user_requests_mcp?user={user_id}")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "accept_follow_request":
            params = accept_follow_request_tool(**arguments)
            user_id = require_user_id()
            if not user_id:
                return [TextContent(type="text", text="Error: Not logged in. Please call the 'login' tool first with your email and password.")]
            data = params.model_dump(exclude_none=True)
            data["adminId"] = user_id
            result = await make_api_request("POST", f"accept_follow_request_mcp" , data = data)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    except httpx.HTTPStatusError as e:
        return [TextContent(type="text", text=f"API Error: {e.response.status_code} - {e.response.text}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

