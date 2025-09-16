// server.js — ESM
import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import fetch from "node-fetch"; // works on Node 16/18+

dotenv.config();

const app = express();
const PORT = process.env.PORT || 4001;

// ---- CORS allow-list: update your Vercel URL ----
const ALLOWED_ORIGINS = [
  "http://localhost:3000",
  "https://<your-vercel-app>.vercel.app" // TODO: replace
  // "https://<your-custom-domain>"       // optional
];

app.use(
  cors({
    origin(origin, cb) {
      if (!origin) return cb(null, true); // curl/postman
      if (ALLOWED_ORIGINS.includes(origin)) return cb(null, true);
      cb(new Error("Not allowed by CORS"));
    }
  })
);

app.use(express.json());

// Tiny request logger
app.use((req, _res, next) => {
  console.log(`[${new Date().toISOString()}] ${req.method} ${req.url}`);
  next();
});

// Health
app.get("/health", (_req, res) =>
  res.status(200).json({ ok: true, ts: Date.now() })
);

// Debug (safe)
app.get("/debug/env", (_req, res) => {
  const k = (process.env.CFBD_KEY || "").trim();
  res.json({ cfbd_present: !!k, cfbd_prefix: k ? k.slice(0, 6) : null, port: String(PORT) });
});

// Helper
async function fetchCfbdGames({ year, week }) {
  const key = (process.env.CFBD_KEY || "").trim();
  if (!key) throw new Error("CFBD_KEY missing");
  const url = `https://api.collegefootballdata.com/games?year=${year}&week=${week}&seasonType=regular`;
  const r = await fetch(url, {
    headers: { Authorization: `Bearer ${key}`, Accept: "application/json" }
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`CFBD ${r.status}: ${body.slice(0, 200)}`);
  }
  return r.json();
}

// /scrape?league=ncaaf&year=2025&week=2
app.get("/scrape", async (req, res) => {
  try {
    const league = String(req.query.league || "").toLowerCase();
    const year   = String(req.query.year   || "2025");
    const week   = String(req.query.week   || "");

    if (!league) return res.status(400).json({ error: "missing_league" });
    if (league !== "ncaaf") return res.status(400).json({ error: "unsupported_league" });
    if (!week)   return res.status(400).json({ error: "missing_week" });

    const games = await fetchCfbdGames({ year, week });
    if (!Array.isArray(games) || games.length === 0) return res.status(204).send();

    res.json({ ok: true, league, year, week, count: games.length, games });
  } catch (err) {
    console.error("[scrape] error", err?.message || err);
    res.status(500).json({ error: "scrape_failed", detail: String(err?.message || err) });
  }
});

app.listen(PORT, () => console.log(`scraper listening on ${PORT}`));
