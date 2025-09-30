// analyzer/src/server.ts
import express from "express";
import analyzeRouter from "./routes/analyze";

const app = express();
app.use(express.json());
app.get("/healthz", (_req, res) => res.json({ ok: true }));
app.use("/", analyzeRouter);

app.listen(process.env.PORT || 4002, () =>
  console.log("analyzer listening", process.env.PORT || 4002)
);
