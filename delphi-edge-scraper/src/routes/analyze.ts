import { Router } from "express";
const router = Router();

type Game = {
  id: string;
  league: string;
  week: number | string;
  home: string;
  away: string;
  homeRank?: number;
  awayRank?: number;
  homePrevPts?: number;
  awayPrevPts?: number;
  kickoff?: string;
};

router.post("/analyze", (req, res) => {
  const games: Game[] = req.body?.games ?? [];

  const insights = games.map(g => {
    const rankDelta =
      (typeof g.homeRank === "number" ? g.homeRank : 50) -
      (typeof g.awayRank === "number" ? g.awayRank : 50);

    const paceHint =
      (g.homePrevPts ?? 20) + (g.awayPrevPts ?? 20) >= 50 ? "faster" : "slower";

    const lean =
      rankDelta < -5 ? `${g.home} favored` :
      rankDelta >  5 ? `${g.away} live dog` :
                       "toss-up";

    return {
      gameId: g.id,
      matchup: `${g.away} @ ${g.home}`,
      kickoff: g.kickoff ?? null,
      model: {
        rankDelta,
        paceHint,
      },
      summary: `${lean}; likely ${paceHint} pace.`,
      flags: [
        ...(Math.abs(rankDelta) >= 10 ? ["rank_gap"] : []),
        ...(paceHint === "faster" ? ["pace_over"] : []),
      ]
    };
  });

  return res.json({ insights });
});

export default router;
