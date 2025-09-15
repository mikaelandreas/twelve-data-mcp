// server.js — MCP over HTTP/SSE for Twelve Data OHLC
// One endpoint: /sse (Server-Sent Events transport that ChatGPT connectors use)

const express = require("express");
const fetch = require("node-fetch");
const { Server } = require("@modelcontextprotocol/sdk/server");

// ---- Config ----
const API = "https://api.twelvedata.com/time_series";
const KEY = process.env.TWELVE_API_KEY; // set on Render

// Normalize TD -> [{t,o,h,l,c,v}]
function normalize(values = []) {
  return values.map(d => ({
    t: d.datetime,
    o: +d.open,
    h: +d.high,
    l: +d.low,
    c: +d.close,
    v: +(d.volume ?? 0),
  }));
}

// Aggregate 1m -> 2m
function to2m(bars) {
  const out = [];
  for (let i = 0; i < bars.length; i += 2) {
    const a = bars[i], b = bars[i + 1];
    if (!a || !b) break;
    out.push({
      t: a.t,
      o: a.o,
      h: Math.max(a.h, b.h),
      l: Math.min(a.l, b.l),
      c: b.c,
      v: (a.v || 0) + (b.v || 0),
    });
  }
  return out;
}

// Define the MCP tool
const getOHLC = {
  name: "get_ohlc",
  description: "Fetch OHLC from Twelve Data. Returns [{t,o,h,l,c,v}] (UTC, oldest→newest). Intervals: 1min,5min,15min,1h,1day, and '2m' (built from 1-min).",
  inputSchema: {
    type: "object",
    properties: {
      symbol: { type: "string", description: "EUR/USD, BTC/USD, AAPL" },
      interval: { type: "string", description: "e.g., 15min or 2m" },
      limit: { type: "number", default: 100 }
    },
    required: ["symbol", "interval"]
  },
  handler: async ({ symbol, interval, limit = 100 }) => {
    if (!KEY) throw new Error("TWELVE_API_KEY not set on server");
    const wants2m = interval === "2m";
    const tdInt = wants2m ? "1min" : interval; // TD uses 1min/15min/1h/etc
    const outsize = wants2m ? Math.min(200, limit * 2) : Math.min(100, limit);

    const url = `${API}?symbol=${encodeURIComponent(symbol)}&interval=${tdInt}&outputsize=${outsize}&apikey=${KEY}`;
    const r = await fetch(url);
    const j = await r.json();
    if (j.status === "error") throw new Error(j.message || "Twelve Data error");

    let bars = normalize(j.values || []).reverse(); // oldest→newest
    if (wants2m) bars = to2m(bars);
    bars = bars.slice(-limit);

    return { symbol, interval: wants2m ? "2m" : interval, data: bars };
  }
};

// --- Minimal HTTP/SSE bridge for MCP ---
const app = express();
const server = require("http").createServer(app);

// Create an MCP server instance with our tool
const mcp = new Server({ name: "twelve-data-ohlc", version: "0.1.0", tools: [getOHLC] });

// Health check
app.get("/", (_req, res) => res.send("MCP Twelve Data server is running"));

// SSE endpoint (what you’ll paste into ChatGPT)
app.get("/sse", (req, res) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.flushHeaders?.();

  // Tie MCP's stdio-like streams to this HTTP response
  const { input, output } = mcp.connect(); // returns duplex-like streams

  // Anything MCP outputs -> send as SSE "data" lines
  output.on("data", (chunk) => res.write(`data: ${chunk.toString()}\n\n`));
  output.on("end", () => res.end());

  // Client → MCP (ChatGPT will POST messages separately; the SDK wires it up internally)
  req.on("close", () => res.end());
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => console.log(`MCP HTTP server on :${PORT}`));
