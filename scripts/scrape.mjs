#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { argv } from "node:process";
const args = Object.fromEntries(
  argv.slice(2).map(a => { const [k,v] = a.replace(/^--/,"").split("="); return [k, v ?? true]; })
);
const league = String(args.league ?? "ncaaf");
const week   = String(args.week   ?? "2");
const year   = String(args.year   ?? new Date().getFullYear());

const mockPath = join(process.cwd(), "src", "mock", "games.dev.json");
const mock = JSON.parse(readFileSync(mockPath, "utf8"));
const games = mock.games.filter(g =>
  String(g.league) === league &&
  String(g.week) === week &&
  (!g.year || String(g.year) === year)
);
console.log(JSON.stringify({ games: games.length ? games : mock.games }));