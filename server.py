# ---- Health check for Render ----
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.applications import Starlette

async def health(_req):
    return PlainTextResponse("ok")

# IMPORTANT: Mount MCP SSE at /sse/
app = Starlette(routes=[
    Route("/health", health),
    Mount("/sse/", app=mcp.sse_app()),  # <-- this is the only MCP endpoint
])
