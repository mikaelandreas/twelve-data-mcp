# server.py — MCP over HTTP/SSE for Twelve Data OHLC
import os, httpx
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

API = "https://api.twelvedata.com/time_series"
KEY = os.environ.get("TWELVE_API_KEY")

mcp = FastMCP("twelve-data-ohlc", version="0.1.0")

def agg_2m(bars):
    out = []
    for i in range(0, len(bars), 2):
        if i + 1 >= len(bars):
            break
        a, b = bars[i], bars[i + 1]
        out.append({
            "t": a["t"],
            "o": a["o"],
            "h": max(a["h"], b["h"]),
            "l": min(a["l"], b["l"]),
            "c": b["c"],
            "v": (a.get("v", 0) + b.get("v", 0)),
        })
    return out

@mcp.tool()
async def get_ohlc(symbol: str, interval: str, limit: int = 100) -> dict:
    """
    Normalized OHLCV [{t,o,h,l,c,v}] in UTC, oldest→newest.
    Intervals: 1min,5min,15min,30min,45min,1h,1day, etc. Use '2m' for 2-minute (aggregated from 1min).
    """
    if not KEY:
        raise RuntimeError("TWELVE_API_KEY is not set on the server")

    wants_2m = (interval == "2m")
    td_interval = "1min" if wants_2m else interval  # Twelve Data naming
    outsize = min(200, limit * 2) if wants_2m else min(100, limit)

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(API, params={
            "symbol": symbol,
            "interval": td_interval,
            "outputsize": outsize,
            "apikey": KEY
        })
        j = r.json()

    if j.get("status") == "error":
        raise RuntimeError(j.get("message", "Twelve Data error"))

    vals = j.get("values", [])
    bars = [{
        "t": d["datetime"],
        "o": float(d["open"]),
        "h": float(d["high"]),
        "l": float(d["low"]),
        "c": float(d["close"]),
        "v": float(d.get("volume", 0)),
    } for d in vals]
    bars.reverse()  # TD returns newest-first

    if wants_2m:
        bars = agg_2m(bars)

    return {"symbol": symbol, "interval": "2m" if wants_2m else interval, "data": bars[-limit:]}

# simple health endpoints
async def health(_req): return PlainTextResponse("ok")
async def info(_req):   return JSONResponse({"service":"twelve-data-ohlc","status":"up"})

# Expose FastMCP's SSE app at /sse and add health routes
app = Starlette(routes=[
    Mount("/sse", app=mcp.sse_app()),
    Route("/", info),
    Route("/health", health),
])
