// *** DELPHI-SCRAPER BOOT (server.js/CJS) ***
console.log('*** DELPHI-SCRAPER BOOT (server.js) ***');
console.log('CWD=', process.cwd());
console.log('FILE=', __filename);

require('dotenv').config();
const express = require('express');
const cors = require('cors');
const fetch = require('node-fetch');
const { createLogger, transports, format } = require('winston');

const app = express();
app.use(express.json());
app.use(cors({ origin: ['http://localhost:3000'] }));

const log = createLogger({
  level: 'debug',
  transports: [new transports.Console({ format: format.simple() })],
});

const PORT = Number(process.env.PORT || 4001);
const CFBD_YEAR = process.env.CFBD_YEAR || '2025';
const CFBD_KEY = process.env.CFBD_KEY || '';

console.log('[boot] CFBD_KEY present?', !!CFBD_KEY);
console.log('[boot] PORT:', PORT);

// sanity routes
app.get('/', (_req, res) => res.type('text').send('Delphi scraper alive'));
app.get('/healthz', (_req, res) => res.json({ ok: true }));

// GET /scrape?ncaaf_week=2&year=2025
app.get('/scrape', async (req, res) => {
  try {
    const year = String(req.query.year ?? CFBD_YEAR);
    const week = String(req.query.ncaaf_week ?? '2');

    if (!CFBD_KEY) {
      log.error('CFBD_KEY missing');
      return res.status(500).json({ error: 'missing_cfbd_key' });
    }

    const url = `https://api.collegefootballdata.com/games?year=${year}&week=${week}&seasonType=regular`;
    log.info(`CFBD GET ${url}`);

    const resp = await fetch(url, { headers: { Authorization: `Bearer ${CFBD_KEY}` } });
    log.info(`CFBD status: ${resp.status} ${resp.statusText}`);

    const bodyText = await resp.text();
    if (!resp.ok) {
      log.error(`CFBD error body: ${bodyText}`);
      return res.status(resp.status).send(bodyText);
    }

    res.setHeader('Content-Type', 'application/json');
    return res.status(200).send(bodyText);
  } catch (err) {
    log.error(`SCRAPE_EXCEPTION ${err.stack || err}`);
    return res.status(500).json({ error: 'scrape_exception', message: String(err) });
  }
});

app.listen(PORT, () => {
  log.info(`scraper listening on ${PORT}`);
});
