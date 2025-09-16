// server.js (ESM)

import express from "express";
import dotenv from "dotenv";
dotenv.config();

const app = express();
const PORT = process.env.PORT || 4001;

// Boot logs
console.log("[boot] CFBD_KEY present?", !!(process.env.CFBD_KEY || "").trim());
console.log("[boot] PORT:", PORT);

// Health
app.get("/health", (_req, res) => {
  res.json({ ok: true, service: "scraper", ts: new Date().toISOString() });
});

// Debug env
app.get("/debug/env", (_req, res) => {
  const k = (process.env.CFBD_KEY || "").trim();
  res.json({
    cfbd_present: !!k,
    cfbd_prefix: k ? k.slice(0, 6) : null,
    port: String(PORT),
  });
});

// Scrape: /scrape?league=ncaaf&year=2025&week=2
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
    console.log("[scrape] GET", url, "| auth=Bearer", key.slice(0, 6) + "...");

    const r = await fetch(url, {
      headers: {
        Authorization: `Bearer ${key}`,
        Accept: "application/json",
      },
    });

    if (!r.ok) {
      const body = await r.text().catch(() => "");
      console.error("[scrape] CFBD error", r.status, body.slice(0, 300));
      return res
        .status(502)
        .json({ error: "cfbd_bad_status", status: r.status, body: body.slice(0, 300) });
    }

    const data = await r.json();
    console.log("[scrape] OK count=", Array.isArray(data) ? data.length : "n/a");
    return res.json({ league, year, week, count: Array.isArray(data) ? data.length : 0, games: data });
  } catch (err) {
    console.error("[scrape] EXCEPTION", err?.message || err);
    return res.status(500).json({ error: "scrape_failed", detail: String(err?.message || err) });
  }
});

app.listen(PORT, () => console.log(`scraper listening on ${PORT}`));
