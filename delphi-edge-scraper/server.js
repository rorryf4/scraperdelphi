// server.js (CommonJS, Render-safe)
const express = require("express");
const cors = require("cors");
require("dotenv").config();

// Ensure fetch exists (Node 20+ has global fetch; fallback to node-fetch if needed)
let _fetch = global.fetch;
if (typeof _fetch !== "function") {
  _fetch = (...args) => import("node-fetch").then(({ default: f }) => f(...args));
}
const fetch = _fetch;

const app = express();

// ---- CORS allow-list ----
// Replace <your-vercel-app> after you deploy the frontend
const ALLOWED_ORIGINS = [
  "http://localhost:3000",
  "https://<your-vercel-app>.vercel.app",
];

app.use(cors({
  origin(origin, cb) {
    if (!origin) return cb(null, true); // curl/postman
    if (ALLOWED_ORIGINS.includes(origin)) return cb(null, true);
    return cb(new Error("Not allowed by CORS"));
  }
}));

app.use(express.json());

// ---- health check ----
app.get("/health", (_req, res) => {
  res.status(200).json({ ok: true, ts: Date.now() });
});

// ---- debug env (do NOT expose keys) ----
app.get("/debug/env", (_req, res) => {
  const k = (process.env.CFBD_KEY || "").trim();
  res.json({ cfbd_present: !!k, port: String(process.env.PORT || "") });
});

// ---- scrape ----
// Example: /scrape?league=ncaaf&year=2025&week=2
app.get("/scrape", async (req, res) => {
  try {
    const league = String(req.query.league || "").toLowerCase();
    const year   = String(req.query.year   || "2025");
    const week   = String(req.query.week   || "");

    if (!league) return res.status(400).json({ error: "missing_league" });
    if (league !== "ncaaf") return res.status(400).json({ error: "unsupported_league" });
    if (!week)   return res.status(400).json({ error: "missing_week" });

    const key = (process.env.CFBD_KEY || "").trim();
    if (!key) return res.status(500).json({ error: "missing_cfbd_key" });

    const url = `https://api.collegefootballdata.com/games?year=${year}&week=${week}&seasonType=regular`;
    console.log("[scrape] GET", url);

    const r = await fetch(url, {
      headers: { Authorization: `Bearer ${key}`, Accept: "application/json" },
    });

    if (!r.ok) {
      const body = await r.text().catch(() => "");
      console.error("[scrape] CFBD error", r.status, body.slice(0, 300));
      return res.status(502).json({ error: "cfbd_bad_status", status: r.status, body: body.slice(0, 300) });
    }

    const data = await r.json();
    const count = Array.isArray(data) ? data.length : 0;
    console.log("[scrape] OK count=", count);
    if (count === 0) return res.status(204).send(); // no content
    return res.json({ ok: true, league, year, week, count, games: data });
  } catch (err) {
    console.error("[scrape] EXC", err?.message || err);
    return res.status(500).json({ error: "scrape_failed", detail: String(err?.message || err) });
  }
});

// ---- start ----
// IMPORTANT: Render injects PORT; you MUST listen on it.
const PORT = process.env.PORT || 4001;
app.listen(PORT, "0.0.0.0", () => {
  console.log(`scraper listening on ${PORT}`);
});
