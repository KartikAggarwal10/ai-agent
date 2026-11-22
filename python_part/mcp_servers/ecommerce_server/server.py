"""
MCP Server for Ecommerce Website
Exposes ecommerce API as MCP tools for the agent
"""
import os
import json
import asyncio
from typing import Any, Dict, List, Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from pydantic import BaseModel
import httpx
# Configuration - UPDATE THESE WITH YOUR ACTUAL API ENDPOINTS
ECOMMERCE_API_BASE = os.getenv("ECOMMERCE_API_BASE", "http://localhost:5000/")
ECOMMERCE_API_KEY = os.getenv("ECOMMERCE_API_KEY", "your-api-key")
# Safe here because this is a stdio server: one process per client connection.
_session: Dict[str, Any] = {
    "user_id": None,
    "token": None,
    "email":None,
    "password" : None,  # if your API returns an auth token on login, store that too
    "isdm" : None
}
def require_user_id() -> str:
    """Fetch the logged-in user_id, or set a default user."""
    if not _session.get("user_id"):
        _session["user_id"] = "687126b78d8c2fa3b062a249"
        _session["email"] = "r@g.c"
        _session["password"] = "d"
        _session["isdm"] = False

    return _session["user_id"]

def require_admin_id() -> str:
    """Fetch the logged-in user_id, or set a default user."""
    if not _session.get("user_id"):
        _session["user_id"] = "686a5f2c6800c12ab460e50d"
        _session["email"] = "u"
        _session["password"] = "y"
        _session["isdm"] = True

    return _session["user_id"]

class GetProductsParams(BaseModel):
    limit: int = 20
    category: Optional[str] = None
    search: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    in_stock_only: bool = True 


class GetProductParams(BaseModel):
    product_id: str


class CreateOrderParams(BaseModel):
    user_id: str
    items: List[Dict[str, Any]]  # [{"product_id": "xxx", "quantity": 2."product_name" : str}]
    shipping_address: Dict[str, str]
    billing_address: Optional[Dict[str, str]] = None
    payment_method: str = "card"


class GetOrderParams(BaseModel):
    order_id: str
    user_id : str

class GetUserOrdersParams(BaseModel):
    user_id: str
    limit: int = 20
    offset: int = 0
    status: Optional[str] = None


class UpdateOrderStatusParams(BaseModel):
    user_id:str
    order_id: str
    status: str  # pending, confirmed, shipped, delivered, cancelled


class CreateProductParams(BaseModel):
    name: str
    description: str
    price: float
    category: str
    stock: int
    images: List[str]
class loginUserParams(BaseModel):
    email : str
    password : str

async def make_api_request(method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
    """Make HTTP request to ecommerce API"""
    headers = {
        "Authorization": f"Bearer {ECOMMERCE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{ECOMMERCE_API_BASE}{endpoint}"
        response = await client.request(method, url, headers=headers, json=data, params=params)
        response.raise_for_status()
        return response.json()


server = Server("ecommerce-mcp-server")

## login,signup,create order, check (order,orders), product details, search for similar products , see products -> playwright
@server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="get_products",
            description="Get list of products with optional filters",
            inputSchema=GetProductsParams.model_json_schema(),
        ),
        Tool(
            name="get_product",
            description="Get a single product by ID with full details",
            inputSchema=GetProductParams.model_json_schema(),
        ),
        Tool(
            name="create_order",
            description="Create a new order",
            inputSchema=CreateOrderParams.model_json_schema(),
        ),
        Tool(
            name="get_order",
            description="Get order details by ID",
            inputSchema=GetOrderParams.model_json_schema(),
        ),
        Tool(
            name="get_user_orders",
            description="Get all orders for a user",
            inputSchema=GetUserOrdersParams.model_json_schema(),
        ),
        Tool(
            name="update_order_status",
            description="Update order status (admin)",
            inputSchema=UpdateOrderStatusParams.model_json_schema(),
        ),
        Tool(
            name="create_product",
            description="Create a new product (admin)",
            inputSchema=CreateProductParams.model_json_schema(),
        ),
        Tool(
            name="login",
            description="login to your account",
            inputSchema=loginUserParams.model_json_schema(),
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        if name == "get_products":
            params = GetProductsParams(**arguments)
            print("params = " + str(params))
            query_params = params.model_dump(exclude_none=True)
            result = await make_api_request("GET", "products", params=query_params)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_product":
            params = GetProductParams(**arguments)
            result = await make_api_request("GET", f"products/{params.product_id}")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "create_order":

            params = CreateOrderParams(**arguments)
            data = params.model_dump(exclude_none=True)
            result = await make_api_request("POST", "orders", data=data)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_order":
            params = GetOrderParams(**arguments)
            result = await make_api_request("GET", f"orders/{params.order_id}/{params.user_id}")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_user_orders":
            params = GetUserOrdersParams(**arguments)
            query_params = params.model_dump(exclude_none=True)
            result = await make_api_request("GET", "orders", params=query_params)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "update_order_status":
            params = UpdateOrderStatusParams(**arguments)
            data = {"status": params.status}
            result = await make_api_request("PATCH", f"orders/{params.order_id}/{params.user_id}", data=data)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "create_product":
            params = CreateProductParams(**arguments)
            data = params.model_dump(exclude_none=True)
            result = await make_api_request("POST", "products", data=data)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == 'login':
            params = loginUserParams(**arguments)
            result = await make_api_request("POST", f"api/user/{params.email}/{params.password}")
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