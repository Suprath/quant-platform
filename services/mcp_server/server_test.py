from mcp.server.fastmcp import FastMCP
import httpx
from starlette.middleware.cors import CORSMiddleware

mcp = FastMCP("Kira")

@mcp.tool()
async def ping() -> str:
    """Check if the server is alive."""
    return "pong"

if hasattr(mcp, "sse_app"):
    app = mcp.sse_app()
else:
    app = None

if app is not None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
