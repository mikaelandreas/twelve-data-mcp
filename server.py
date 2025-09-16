# server.py — MCP over HTTP/SSE for Twelve Data OHLC (with proper health routes)
import os, httpx
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

API = "https://api.twelvedata.com/time_series"
KEY = os.environ.get("TWELVE_API_KEY")

mcp = FastMCP("twelve-data-ohlc")

def agg_2m(bars):
    out = []
    for i in range(0, len(bars), 2):
        if i + 1 >= len(bars): break
        a, b = bars[i], bars[i+1]
        out.append({
            "t": a["t"], "o": a["o"],
            "h": max(a["h"], b["h"]),
            "l": min(a["l"], b["l"]),
            "c": b["c"], "v": (a.get("v",0) + b.get("v",0))
        })
    return out

@mcp.tool()
async def get_ohlc(symbol: str, interval: str, limit: int = 100) -> dict:
    """Return [{t,o,h,l,c,v}] UTC, oldest→newest. Use '2m' to aggregate from 1min."""
    if not KEY:
        raise RuntimeError("TWELVE_API_KEY is not set")
    wants_2m = (interval == "2m")
    td_int = "1min" if wants_2m else interval
    outsize = min(200, limit*2) if wants_2m else min(100, limit)

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(API, params={
            "symbol": symbol, "interval": td_int,
            "outputsize": outsize, "apikey": KEY
        })
        j = r.json()
    if j.get("status") == "error":
        raise RuntimeError(j.get("message", "Twelve Data error"))

    bars = [{
        "t": d["datetime"],
        "o": float(d["open"]), "h": float(d["high"]),
        "l": float(d["low"]),  "c": float(d["close"]),
        "v": float(d.get("volume", 0))
    } for d in (j.get("values") or [])][::-1]  # oldest->newest

    if wants_2m:
        bars = agg_2m(bars)
    return {"symbol": symbol, "interval": ("2m" if wants_2m else interval), "data": bars[-limit:]}

# --- Health + info routes that return 200 (so Render doesn't restart us)
# --- Health + info routes ---
async def health(_req): return PlainTextResponse("ok")
async def info(_req):   return JSONResponse({"service": "twelve-data-ohlc", "status": "up"})

app = Starlette(routes=[
    Route("/", info),                  # human-friendly JSON at root
    Route("/health", health),          # 200 OK for Render health checks
    Mount("/sse/", app=mcp.sse_app()), # MCP SSE endpoint (GET stream + POST messages)
])
