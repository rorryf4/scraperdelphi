// server.js (delphi-scraper)
import express from "express";
import fetch from "node-fetch";
import * as cheerio from "cheerio";
import dotenv from "dotenv";
dotenv.config();
console.log("CFBD_KEY present?", !!process.env.CFBD_KEY);


const key = process.env.CFBD_KEY;
const port = process.env.PORT || 4001;

const app = express();
app.use(express.json());

const YEAR = Number(process.env.CFBD_YEAR || new Date().getFullYear());
const CFBD_KEY = process.env.CFBD_KEY || ""; // free key from collegefootballdata.com
const headersCFBD = CFBD_KEY ? { Authorization: `Bearer ${CFBD_KEY}` } : {};
const HFA = 2.3; // (not used in scraper; handy for analyzer if you want)

function normalize({ league, week, rows }) {
  return {
    league,
    week,
    pulledAt: new Date().toISOString(),
    games: rows.map((r) => ({
      id: r.id,
      home: r.home,
      away: r.away,
      kickoff: r.kickoff,
      market: { spread: Number(r.spread ?? 0), total: Number(r.total ?? 0) },
      teamForm: r.teamForm ?? {},
      notes: r.notes ?? [],
    })),
  };
}

// ---------- Provider A: CFBD (games + lines) ----------
async function cfbdGames(week) {
  const url = `https://api.collegefootballdata.com/games?year=${YEAR}&week=${week}&seasonType=regular&division=fbs`;
  const res = await fetch(url, { headers: headersCFBD });
  if (!res.ok) throw new Error(`CFBD games ${res.status}`);
  return res.json();
}

async function cfbdLines(week) {
  // Book-by-book; we’ll pick the first with spread/total
  const url = `https://api.collegefootballdata.com/lines?year=${YEAR}&week=${week}&seasonType=regular`;
  const res = await fetch(url, { headers: headersCFBD });
  if (!res.ok) throw new Error(`CFBD lines ${res.status}`);
  return res.json();
}

function pickConsensusLine(linesForGame = []) {
  // Choose the first line that provides spread/OU; customize to average if you prefer
  for (const l of linesForGame) {
    const spread = l.spread ?? l.formula ?? null;
    const total = l.overUnder ?? null;
    if (spread != null || total != null) {
      return { spread: Number(spread ?? 0), total: Number(total ?? 0) };
    }
  }
  return { spread: 0, total: 0 };
}

async function fetchViaCfbd(league, week) {
  const [games, odds] = await Promise.all([cfbdGames(week), cfbdLines(week)]);

  // Index odds by home/away pair
  const byMatch = new Map();
  for (const o of odds || []) {
    const key = `${o.homeTeam}__${o.awayTeam}`.toLowerCase();
    const arr = byMatch.get(key) || [];
    arr.push(o);
    byMatch.set(key, arr);
  }

  const rows = (games || []).map((g) => {
    const home = g.home_team;
    const away = g.away_team;
    const kickoffIso = g.start_date ? new Date(g.start_date).toISOString() : new Date().toISOString();
    const key = `${home}__${away}`.toLowerCase();
    const consensus = pickConsensusLine(byMatch.get(key));
    return {
      id: `${league}-${home}-${away}`.toLowerCase().replace(/\s+/g, "-"),
      home,
      away,
      kickoff: kickoffIso,
      spread: consensus.spread,
      total: consensus.total,
      teamForm: {},
      notes: [],
    };
  });

  return normalize({ league, week, rows });
}

// ---------- Provider B: ESPN (unofficial JSON; no key) ----------
async function fetchViaEspn(league, week) {
  const url = `https://site.api.espn.com/apis/v2/sports/football/college-football/scoreboard?week=${week}&dates=${YEAR}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`ESPN ${res.status}`);
  const json = await res.json();

  const rows = [];
  for (const e of json.events || []) {
    const c = e.competitions?.[0];
    if (!c) continue;
    const home = c.competitors?.find((x) => x.homeAway === "home")?.team?.displayName;
    const away = c.competitors?.find((x) => x.homeAway === "away")?.team?.displayName;
    const kickoff = c.date ? new Date(c.date).toISOString() : new Date().toISOString();
    const spread = Number(c.odds?.[0]?.spread ?? 0);
    const total = Number(c.odds?.[0]?.overUnder ?? 0);
    if (home && away) {
      rows.push({
        id: `${league}-${home}-${away}`.toLowerCase().replace(/\s+/g, "-"),
        home,
        away,
        kickoff,
        spread,
        total,
        notes: [],
      });
    }
  }
  return normalize({ league, week, rows });
}

// ---------- Provider C: HTML fallback (stub until you pick a site) ----------
async function fillLinesWithHtml(rows, week) {
  // Choose a site (e.g., VegasInsider/Covers) and add selectors here.
  // Leaving as no-op for now; returns rows unchanged.
  // When ready: fetch page → cheerio.load → build mapping → fill spreads/totals where missing.
  return rows;
}

// ---------- /scrape with fallback chain ----------
app.get("/scrape", async (req, res) => {
  const league = (req.query.league || "ncaaf").toString();
  const week = Number(req.query.week || 1);

  try {
    // Try CFBD first
    let data = await fetchViaCfbd(league, week);

    // Fill any missing odds via ESPN
    const espn = await fetchViaEspn(league, week);
    const idx = new Map(espn.games.map((g) => [`${g.home}__${g.away}`.toLowerCase(), g.market]));
    data.games = data.games.map((g) => {
      if (!g.market.spread && !g.market.total) {
        const m = idx.get(`${g.home}__${g.away}`.toLowerCase());
        if (m) return { ...g, market: m };
      }
      return g;
    });

    // Optional final HTML fill (currently a stub/no-op)
    const rows = await fillLinesWithHtml(
      data.games.map((g) => ({
        id: g.id,
        home: g.home,
        away: g.away,
        kickoff: g.kickoff,
        spread: g.market.spread,
        total: g.market.total,
      })),
      week
    );
    const map = new Map(rows.map((r) => [r.id, r]));
    data.games = data.games.map((g) => {
      const m = map.get(g.id);
      return m ? { ...g, market: { spread: m.spread ?? g.market.spread, total: m.total ?? g.market.total } } : g;
    });

    res.json(data);
  } catch (e) {
    console.error("CFBD failed; falling back to ESPN:", e?.message || e);
    try {
      const data = await fetchViaEspn(league, week);
      res.json(data);
    } catch (e2) {
      console.error("ESPN fallback failed:", e2?.message || e2);
      res.status(502).json({ error: "scrape_failed" });
    }
  }
});

app.get("/health", (_req, res) => res.json({ ok: true, service: "scraper" }));

const PORT = process.env.PORT || 4001;
app.listen(PORT, () => console.log(`scraper listening on ${PORT}`));
