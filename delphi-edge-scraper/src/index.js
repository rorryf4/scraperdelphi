import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import fetch from 'node-fetch';
import winston from 'winston';

// add at very top
console.log('*** DELPHI-SCRAPER BOOT ***');
console.log('CWD=', process.cwd());
console.log('FILE=', import.meta.url);

import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import fetch from 'node-fetch';
import winston from 'winston';

const app = express();
app.use(express.json());
app.use(cors({ origin: ['http://localhost:3000'] }));

const log = winston.createLogger({
  level: 'debug',
  transports: [new winston.transports.Console({ format: winston.format.simple() })]
});

const PORT = process.env.PORT || 4011;

// sanity route to prove it's OUR server
app.get('/', (_req, res) => res.type('text').send('Delphi scraper alive'));

// health
app.get('/healthz', (_req, res) => res.json({ ok: true }));

// (keep your /scrape route as-is)

app.listen(PORT, '127.0.0.1', () => log.info(`scraper listening on http://127.0.0.1:${PORT}`));


const app = express();
app.use(express.json());
app.use(cors({ origin: ['http://localhost:3000'] }));

const log = winston.createLogger({
  level: 'debug',
  transports: [new winston.transports.Console({ format: winston.format.simple() })]
});

const PORT = process.env.PORT || 4001;

app.get('/healthz', (_req, res) => res.json({ ok: true }));

// GET /scrape?ncaaf_week=2&year=2025
app.get('/scrape', async (req, res) => {
  const year = req.query.year || process.env.CFBD_YEAR || '2025';
  const week = req.query.ncaaf_week || '2';
  const key = process.env.CFBD_KEY;

  if (!key) {
    log.error('CFBD_KEY missing');
    return res.status(500).json({ error: 'missing_cfbd_key' });
  }

  // keep params minimal first; we can add more later
  const url = `https://api.collegefootballdata.com/games?year=${year}&week=${week}&seasonType=regular`;
  log.info(`CFBD GET ${url}`);

  try {
    const r = await fetch(url, { headers: { Authorization: `Bearer ${key}` } });
    log.info(`CFBD status: ${r.status} ${r.statusText}`);
    const text = await r.text();

    // Surface exact upstream body for debugging (don’t swallow)
    if (!r.ok) {
      log.error(`CFBD error body: ${text}`);
      return res.status(r.status).send(text);
    }

    // text -> json so we don’t double-parse later
    res.setHeader('Content-Type', 'application/json');
    return res.status(200).send(text);
  } catch (err) {
    log.error(`SCRAPE_EXCEPTION ${err.stack || err}`);
    return res.status(500).json({ error: 'scrape_exception', message: String(err) });
  }
});

app.listen(PORT, () => log.info(`scraper listening on ${PORT}`));
