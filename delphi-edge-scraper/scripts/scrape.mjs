#!/usr/bin/env node
// NO FS. Prints a banner with its exact path, then outputs fixed mock JSON.
import { argv } from "node:process";

// show exactly which file is running
console.error("SCRAPER CLI ACTIVE:", new URL(import.meta.url).pathname.replace(/^\/+/, ""));

const args = Object.fromEntries(
  argv.slice(2).map(a => { const [k,v] = a.replace(/^--/, "").split("="); return [k, v ?? true]; })
);
const league = String(args.league ?? "ncaaf");
const week   = String(args.week   ?? "2");
const year   = String(args.year   ?? new Date().getFullYear());

const MOCK = {
  games: [
    {
      id: "ncaaf-2025-w2-PSU-ILL",
      league: "ncaaf",
      year: 2025,
      week: 2,
      home: "Penn State",
      away: "Illinois",
      homeRank: 12,
      awayRank: 24,
      homePrevPts: 27,
      awayPrevPts: 20,
      kickoff: "2025-09-06T16:30:00Z"
    },
    {
      id: "ncaaf-2025-w2-UT-ISU",
      league: "ncaaf",
      year: 2025,
      week: 2,
      home: "Texas",
      away: "Iowa State",
      homeRank: 8,
      awayRank: 18,
      homePrevPts: 31,
      awayPrevPts: 17,
      kickoff: "2025-09-06T19:00:00Z"
    }
  ]
};

const games = (MOCK.games || []).filter(g =>
  String(g.league) === league &&
  String(g.week) === week &&
  (!g.year || String(g.year) === year)
);

console.log(JSON.stringify({ games: games.length ? games : MOCK.games || [] }));
