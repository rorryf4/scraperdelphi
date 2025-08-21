print(">>> quickstart.py is running...")

# ------------------ Imports ------------------
import csv
import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from datetime import datetime, timezone
import feedparser           # pip install feedparser
import httpx                # pip install httpx
from selectolax.parser import HTMLParser
from pydantic import BaseModel, HttpUrl
import urllib.parse
from urllib.parse import urlsplit, urlunsplit


# ------------------ Data model ------------------
class Article(BaseModel):
    title: str
    url: HttpUrl
    published_at: Optional[datetime] = None
    author: Optional[str] = None
    summary: Optional[str] = None
    tags: Optional[list[str]] = None
    fetched_at: datetime
    source: str

# ------------------ Storage ---------------------
DB_PATH = Path("data/delphi_edge.db")
CSV_PATH = Path("data/articles.csv")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    published_at TEXT,
    author TEXT,
    summary TEXT,
    tags TEXT,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL
);
"""

def init_db():
    print(">>> init_db")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(SCHEMA)

def upsert(articles: List[Article]):
    print(f">>> upsert {len(articles)} rows")
    if not articles:
        return
    with sqlite3.connect(DB_PATH) as conn, conn:
        for a in articles:
            conn.execute(
                """INSERT INTO articles (title, url, published_at, author, summary, tags, fetched_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                     title=excluded.title,
                     published_at=excluded.published_at,
                     author=excluded.author,
                     summary=excluded.summary,
                     tags=excluded.tags,
                     fetched_at=excluded.fetched_at,
                     source=excluded.source;""",
                (
                    a.title, str(a.url),
                    a.published_at.isoformat() if a.published_at else None,
                    a.author, a.summary,
                    ",".join(a.tags) if a.tags else None,
                    a.fetched_at.isoformat(), a.source
                )
            )

def export_csv():
    print(">>> export_csv")
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT title, url, published_at, author, summary, tags, fetched_at, source "
            "FROM articles ORDER BY id DESC"
        ).fetchall()
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["title","url","published_at","author","summary","tags","fetched_at","source"])
        writer.writerows(rows)

# ------------------ RSS ingestion ----------------
def rss_to_articles(feed_url: str, source: str, default_tags: list[str] | None = None) -> list[Article]:
    print(f">>> Fetching RSS: {feed_url}")
    try:
        feed = feedparser.parse(feed_url)
        out: list[Article] = []
        for e in feed.entries:
            title = (e.get("title") or "").strip()
            link  = (e.get("link")  or "").strip()
            if not title or not link:
                continue
            out.append(Article(
                title=title,
                url=link,
                published_at=None,                           # parse later if needed
                author=getattr(e, "author", None),
                summary=getattr(e, "summary", None),
                tags=default_tags,
                fetched_at=datetime.now(timezone.utc),
                source=source
            ))
        print(f">>> RSS {source}: {len(out)} items")
        return out
    except Exception as e:
        print(f">>> RSS Error for {feed_url}: {e}")
        return []

# ------------------ HTML fetch & parse ----------
import json
from urllib.parse import urlparse

def load_feeds_json(path: str = "feeds.json") -> list[dict]:
    """Load an array of {url, source?, tags?} from feeds.json."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
        # Support either a raw list or an object with a top-level list key.
        if isinstance(data, dict):
            # try common keys if user wrapped it
            for k in ("feeds", "items", "data"):
                if isinstance(data.get(k), list):
                    return data[k]
            raise ValueError("feeds.json is an object, expected an array under 'feeds' or 'items'")
        if not isinstance(data, list):
            raise ValueError("feeds.json must be a JSON array")
        return data
    except FileNotFoundError:
        print(">>> feeds.json not found; skipping")
        return []
    except Exception as e:
        print(">>> ERROR loading feeds.json:", e)
        return []

def ingest_feeds_with_logging(feeds: list[dict], label_prefix: str = "") -> list[Article]:
    """Fetch all feeds, print counts, return collected Article objects."""
    collected: list[Article] = []
    for f in feeds:
        url = f.get("url", "").strip()
        if not url:
            continue
        source = (f.get("source") or "").strip()
        if not source:
            # derive "https://host" from the URL
            u = urlparse(url)
            source = f"{u.scheme}://{u.netloc}" if u.scheme and u.netloc else url
        tags = f.get("tags") or []
        items_found = rss_to_articles(url, source, tags if isinstance(tags, list) else [str(tags)])
        # Build a friendly label
        if tags:
            label = " ".join(tags)
        else:
            host = urlparse(url).netloc or source
            label = host
        if label_prefix:
            label = f"{label_prefix} {label}"
        print(f">>> {label}: {len(items_found)} items from {url}")
        collected += items_found
    return collected



def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 DelphiEdgeScraper/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
    }
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def scrape_links(url: str, source: str, link_sel: str, tags: list[str],
                 allow_substrings: list[str] | None = None,
                 deny_substrings: list[str] | None = None) -> list[Article]:
    print(f">>> Scraping HTML: {url}")
    try:
        html = fetch_html(url)
        t = HTMLParser(html)
        out: list[Article] = []

        allow_substrings = allow_substrings or []
        deny_substrings = deny_substrings or [
            "/roster", "/schedule", "/stats", "/tickets", "evenue", "shop.",
            "/media-guide", "/coaches", "/facilities", "calendar", "gatornetwork",
            "/photo", "/gallery", "/podcast", "/video", "/store", "/promo"
        ]

        def looks_like_story(href: str) -> bool:
            h = href.lower()
            if not h.startswith("http"):
                return False
            if not h.startswith(source.lower()):
                return False
            if any(x in h for x in deny_substrings):
                return False
            if allow_substrings and not any(x in h for x in allow_substrings):
                return False
            # heuristic: story slugs usually have hyphens in the last path segment
            last = h.rstrip("/").split("/")[-1]
            return "-" in last and len(last) > 8

        for a in t.css(link_sel):
            title = a.text(strip=True)
            href = a.attributes.get("href", "")
            if not title or not href:
                continue
            if href.startswith("/"):
                href = source.rstrip("/") + href
            if looks_like_story(href):
                out.append(Article(
                    title=title,
                    url=href,
                    published_at=None,
                    author=None,
                    summary=None,
                    tags=tags,
                    fetched_at=datetime.now(timezone.utc),
                    source=source
                ))
        
        print(f">>> HTML {tags[-1] if tags else 'Unknown'}: {len(out)} items")
        return out
    except Exception as e:
        print(f">>> HTML Error for {url}: {e}")
        return []
    
def google_news_feed(query: str, tag: str):
    """
    Build a Google News RSS feed URL for a given search query.
    Example: google_news_feed("Alabama Crimson Tide football", "TEAM Alabama")
    """
    q = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    return (url, "Google News", [tag, "LOCAL"])


def canonicalize(u: str) -> str:
    sp = urlsplit(u)
    # drop query/fragment noise; keep path
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))


# ------------------ Feeds ----------------------
# ESPN (football only) + Reddit CFB
ESPN_NFL = "https://www.espn.com/espn/rss/nfl/news"
ESPN_CFB = "https://www.espn.com/espn/rss/ncf/news"
R_CFB    = "https://www.reddit.com/r/CFB/.rss"

# NFL Teams (your 6)
NFL_TEAM_DOMAINS = [
    ("https://www.buffalobills.com",       ["TEAM","Bills"]),
    ("https://www.miamidolphins.com",      ["TEAM","Dolphins"]),
    ("https://www.patriots.com",           ["TEAM","Patriots"]),
    ("https://www.newyorkjets.com",        ["TEAM","Jets"]),

    ("https://www.baltimoreravens.com",    ["TEAM","Ravens"]),
    ("https://www.bengals.com",            ["TEAM","Bengals"]),
    ("https://www.clevelandbrowns.com",    ["TEAM","Browns"]),
    ("https://www.steelers.com",           ["TEAM","Steelers"]),

    ("https://www.houstontexans.com",      ["TEAM","Texans"]),
    ("https://www.colts.com",              ["TEAM","Colts"]),
    ("https://www.jaguars.com",            ["TEAM","Jaguars"]),
    ("https://www.tennesseetitans.com",    ["TEAM","Titans"]),

    ("https://www.denverbroncos.com",      ["TEAM","Broncos"]),
    ("https://www.chiefs.com",             ["TEAM","Chiefs"]),
    ("https://www.raiders.com",            ["TEAM","Raiders"]),
    ("https://www.chargers.com",           ["TEAM","Chargers"]),

    ("https://www.dallascowboys.com",      ["TEAM","Cowboys"]),
    ("https://www.giants.com",             ["TEAM","Giants"]),
    ("https://www.philadelphiaeagles.com", ["TEAM","Eagles"]),
    ("https://www.commanders.com",         ["TEAM","Commanders"]),

    ("https://www.chicagobears.com",       ["TEAM","Bears"]),
    ("https://www.detroitlions.com",       ["TEAM","Lions"]),
    ("https://www.packers.com",            ["TEAM","Packers"]),
    ("https://www.vikings.com",            ["TEAM","Vikings"]),

    ("https://www.atlantafalcons.com",     ["TEAM","Falcons"]),
    ("https://www.panthers.com",           ["TEAM","Panthers"]),
    ("https://www.neworleanssaints.com",   ["TEAM","Saints"]),
    ("https://www.buccaneers.com",         ["TEAM","Buccaneers"]),

    ("https://www.azcardinals.com",        ["TEAM","Cardinals"]),
    ("https://www.therams.com",            ["TEAM","Rams"]),
    ("https://www.seahawks.com",           ["TEAM","Seahawks"]),
    ("https://www.49ers.com",              ["TEAM","49ers"]),
]

# --- Add Yahoo/CBS Feeds ---
YAHOO_NFL = "https://sports.yahoo.com/nfl/rss.xml"
YAHOO_CFB = "https://sports.yahoo.com/college-football/rss.xml"
CBS_NFL   = "https://www.cbssports.com/rss/headlines/nfl/"
CBS_CFB   = "https://www.cbssports.com/rss/headlines/ncaa-fb/"

# inside main()
print(">>> Yahoo NFL:", end=" ")
ya_nfl = rss_to_articles(YAHOO_NFL, "https://sports.yahoo.com", ["Yahoo","NFL"])
print(f"{len(ya_nfl)} items from {YAHOO_NFL}")
items += ya_nfl

print(">>> Yahoo CFB:", end=" ")
ya_cfb = rss_to_articles(YAHOO_CFB, "https://sports.yahoo.com", ["Yahoo","CFB"])
print(f"{len(ya_cfb)} items from {YAHOO_CFB}")
items += ya_cfb

print(">>> CBS NFL:", end=" ")
cbs_nfl = rss_to_articles(CBS_NFL, "https://www.cbssports.com", ["CBS","NFL"])
print(f"{len(cbs_nfl)} items from {CBS_NFL}")
items += cbs_nfl

print(">>> CBS CFB:", end=" ")
cbs_cfb = rss_to_articles(CBS_CFB, "https://www.cbssports.com", ["CBS","CFB"])
print(f"{len(cbs_cfb)} items from {CBS_CFB}")
items += cbs_cfb


# SEC school archives (HTML) - Fixed with proper tuple structure
SEC_ARCHIVES = [
    # Original three
    ("https://lsusports.net/sports/fb/news/", "https://lsusports.net", "a[href*='/news/']", ["TEAM","LSU"], [], []),
    ("https://rolltide.com/sports/football/archives", "https://rolltide.com", "a[href*='/news/']", ["TEAM","Alabama"], [], []),
    ("https://georgiadogs.com/sports/football/archives", "https://georgiadogs.com", "a[href*='/news/']", ["TEAM","Georgia"], [], []),
    # New ones
    ("https://gamecocksonline.com/sports/football/news/", "https://gamecocksonline.com", "a[href*='/news/']", ["TEAM","South Carolina"], [], []),
    ("https://arkansasrazorbacks.com/sport/m-footbl/", "https://arkansasrazorbacks.com", "main a[href]", ["TEAM","Arkansas"], [], []),
    ("https://auburntigers.com/sports/football/news", "https://auburntigers.com", "a[href*='/news/']", ["TEAM","Auburn"]),
    ("https://12thman.com/sports/football/news", "https://12thman.com", "a[href*='/news/']", ["TEAM","Texas A&M"]),
    ("https://olemisssports.com/sports/football/news", "https://olemisssports.com", "a[href*='/news/']", ["TEAM","Ole Miss"]),
    ("https://hailstate.com/sports/football/news", "https://hailstate.com", "a[href*='/news/']", ["TEAM","Mississippi State"]),
    ("https://mutigers.com/sports/football/news", "https://mutigers.com", "a[href*='/news/']", ["TEAM","Missouri"]),
    ("https://ukathletics.com/sports/football/news", "https://ukathletics.com", "a[href*='/news/']", ["TEAM","Kentucky"]),
    ("https://utsports.com/sports/football/news", "https://utsports.com", "a[href*='/news/']", ["TEAM","Tennessee"]),
    ("https://vucommodores.com/sports/football/news", "https://vucommodores.com", "a[href*='/news/']", ["TEAM","Vanderbilt"]),
]

BIG10_ARCHIVES = [
    # Core Big Ten (legacy)
    ("https://mgoblue.com/sports/football",            "https://mgoblue.com",            "a[href*='/news/']", ["TEAM","Michigan"]),
    ("https://ohiostatebuckeyes.com/sports/football",  "https://ohiostatebuckeyes.com",  "a[href*='/news/']", ["TEAM","Ohio State"]),
    ("https://gopsusports.com/sports/football",        "https://gopsusports.com",        "a[href*='/news/']", ["TEAM","Penn State"]),
    ("https://uwbadgers.com/sports/football",          "https://uwbadgers.com",          "a[href*='/news/']", ["TEAM","Wisconsin"]),
    ("https://hawkeyesports.com/sports/football",      "https://hawkeyesports.com",      "a[href*='/news/']", ["TEAM","Iowa"]),
    ("https://msuspartans.com/sports/football",        "https://msuspartans.com",        "a[href*='/news/']", ["TEAM","Michigan State"]),
    ("https://gophersports.com/sports/football",       "https://gophersports.com",       "a[href*='/news/']", ["TEAM","Minnesota"]),
    ("https://fightingillini.com/sports/football",     "https://fightingillini.com",     "a[href*='/news/']", ["TEAM","Illinois"]),
    ("https://iuhoosiers.com/sports/football",         "https://iuhoosiers.com",         "a[href*='/news/']", ["TEAM","Indiana"]),
    ("https://purduesports.com/sports/football/news",  "https://purduesports.com",       "a[href*='/sports/football/']", ["TEAM","Purdue"]),
    ("https://nusports.com/sports/football",           "https://nusports.com",           "a[href*='/news/']", ["TEAM","Northwestern"]),
    ("https://huskers.com/sports/football",            "https://huskers.com",            "a[href*='/news/']", ["TEAM","Nebraska"]),
    ("https://umterps.com/sports/football",            "https://umterps.com",            "a[href*='/news/']", ["TEAM","Maryland"]),
    ("https://scarletknights.com/sports/football",     "https://scarletknights.com",     "a[href*='/news/']", ["TEAM","Rutgers"]),

    # Big Ten expansion schools
    ("https://goducks.com/sports/football",            "https://goducks.com",            "a[href*='/news/']", ["TEAM","Oregon"]),
    ("https://gohuskies.com/sports/football",          "https://gohuskies.com",          "a[href*='/news/']", ["TEAM","Washington"]),
    ("https://usctrojans.com/sports/football",         "https://usctrojans.com",         "a[href*='/news/']", ["TEAM","USC"]),
    ("https://uclabruins.com/sports/football",         "https://uclabruins.com",         "a[href*='/news/']", ["TEAM","UCLA"]),
]

# --- Big 12 Football Team Feeds (Sidearm) ---
BIG12_ARCHIVES = [
    # Texas
    ("https://texassports.com/sports/football/news", "https://texassports.com", ["TEAM","Texas"]),
    # Baylor
    ("https://baylorbears.com/sports/football/news", "https://baylorbears.com", ["TEAM","Baylor"]),
    # Oklahoma State
    ("https://okstate.com/sports/football/news", "https://okstate.com", ["TEAM","Oklahoma State"]),
    # TCU
    ("https://gofrogs.com/sports/football/news", "https://gofrogs.com", ["TEAM","TCU"]),
    # Texas Tech
    ("https://texastech.com/sports/football/news", "https://texastech.com", ["TEAM","Texas Tech"]),
    # Kansas
    ("https://kuathletics.com/sports/football/news", "https://kuathletics.com", ["TEAM","Kansas"]),
    # Kansas State
    ("https://kstatesports.com/sports/football/news", "https://kstatesports.com", ["TEAM","Kansas State"]),
    # Iowa State
    ("https://cyclones.com/sports/football/news", "https://cyclones.com", ["TEAM","Iowa State"]),
    # UCF
    ("https://ucfknights.com/sports/football/news", "https://ucfknights.com", ["TEAM","UCF"]),
    # Houston
    ("https://uhcougars.com/sports/football/news", "https://uhcougars.com", ["TEAM","Houston"]),
    # BYU
    ("https://byucougars.com/sports/football/news", "https://byucougars.com", ["TEAM","BYU"]),
    # Cincinnati
    ("https://gobearcats.com/sports/football/news", "https://gobearcats.com", ["TEAM","Cincinnati"]),
]

# --- ACC Football Team Feeds (Sidearm) ---
ACC_ARCHIVES = [
    # Core ACC
    ("https://clemsontigers.com/sports/football/news",      "https://clemsontigers.com",      ["TEAM","Clemson"]),
    ("https://seminoles.com/sports/football/news",          "https://seminoles.com",          ["TEAM","Florida State"]),
    ("https://miamihurricanes.com/sports/football/news",    "https://miamihurricanes.com",    ["TEAM","Miami"]),
    ("https://goheels.com/sports/football/news",            "https://goheels.com",            ["TEAM","North Carolina"]),
    ("https://gopack.com/sports/football/news",             "https://gopack.com",             ["TEAM","NC State"]),
    ("https://goduke.com/sports/football/news",             "https://goduke.com",             ["TEAM","Duke"]),
    ("https://virginiasports.com/sports/football/news",     "https://virginiasports.com",     ["TEAM","Virginia"]),
    ("https://hokiesports.com/sports/football/news",        "https://hokiesports.com",        ["TEAM","Virginia Tech"]),
    ("https://ramblinwreck.com/sports/football/news",       "https://ramblinwreck.com",       ["TEAM","Georgia Tech"]),
    ("https://gocards.com/sports/football/news",            "https://gocards.com",            ["TEAM","Louisville"]),
    ("https://pittsburghpanthers.com/sports/football/news", "https://pittsburghpanthers.com", ["TEAM","Pitt"]),
    ("https://cuse.com/sports/football/news",               "https://cuse.com",               ["TEAM","Syracuse"]),
    ("https://bceagles.com/sports/football/news",           "https://bceagles.com",           ["TEAM","Boston College"]),
    ("https://godeacs.com/sports/football/news",            "https://godeacs.com",            ["TEAM","Wake Forest"]),

    # ACC newcomers (2024+)
    ("https://calbears.com/sports/football/news",           "https://calbears.com",           ["TEAM","Cal"]),
    ("https://smumustangs.com/sports/football/news",        "https://smumustangs.com",        ["TEAM","SMU"]),
    ("https://gostanford.com/sports/football/news",         "https://gostanford.com",         ["TEAM","Stanford"]),
]

# --- Pac schools (current & recent members) ---
PAC_ARCHIVES = [
    ("https://goducks.com/sports/football/news",        "https://goducks.com",        ["TEAM","Oregon"]),
    ("https://gohuskies.com/sports/football/news",      "https://gohuskies.com",      ["TEAM","Washington"]),
    ("https://usctrojans.com/sports/football/news",     "https://usctrojans.com",     ["TEAM","USC"]),
    ("https://uclabruins.com/sports/football/news",     "https://uclabruins.com",     ["TEAM","UCLA"]),

    ("https://calbears.com/sports/football/news",       "https://calbears.com",       ["TEAM","Cal"]),
    ("https://gostanford.com/sports/football/news",     "https://gostanford.com",     ["TEAM","Stanford"]),

    ("https://arizonawildcats.com/sports/football/news","https://arizonawildcats.com",["TEAM","Arizona"]),
    ("https://thesundevils.com/sports/football/news",   "https://thesundevils.com",   ["TEAM","Arizona State"]),
    ("https://cubuffs.com/sports/football/news",        "https://cubuffs.com",        ["TEAM","Colorado"]),
    ("https://utahutes.com/sports/football/news",       "https://utahutes.com",       ["TEAM","Utah"]),

    ("https://osubeavers.com/sports/football/news",     "https://osubeavers.com",     ["TEAM","Oregon State"]),
    ("https://wsucougars.com/sports/football/news",     "https://wsucougars.com",     ["TEAM","Washington State"]),
]

# --- Mountain West ---
MWC_ARCHIVES = [
    ("https://broncosports.com/sports/football/news",       "https://broncosports.com",       ["TEAM","Boise State"]),
    ("https://themw.com/sports/football/news",              "https://themw.com",               ["LEAGUE","Mountain West"]),  # conference hub
    ("https://golobos.com/sports/football/news",            "https://golobos.com",             ["TEAM","New Mexico"]),
    ("https://unlvrebels.com/sports/football/news",         "https://unlvrebels.com",          ["TEAM","UNLV"]),
    ("https://goaztecs.com/sports/football/news",           "https://goaztecs.com",            ["TEAM","San Diego State"]),
    ("https://sjsuspartans.com/sports/football/news",       "https://sjsuspartans.com",        ["TEAM","San Jose State"]),
    ("https://nevadawolfpack.com/sports/football/news",     "https://nevadawolfpack.com",      ["TEAM","Nevada"]),
    ("https://goairforcefalcons.com/sports/football/news",  "https://goairforcefalcons.com",   ["TEAM","Air Force"]),
    ("https://csurams.com/sports/football/news",            "https://csurams.com",             ["TEAM","Colorado State"]),
    ("https://gozags.com",                                   "https://gozags.com",              ["TEAM","(ignore)"]),  # guardrail example; not FBS football
    ("https://gowyo.com/sports/football/news",              "https://gowyo.com",               ["TEAM","Wyoming"]),
    ("https://utahstateaggies.com/sports/football/news",    "https://utahstateaggies.com",     ["TEAM","Utah State"]),
    ("https://fresnostatebulldogs.com/sports/football/news","https://fresnostatebulldogs.com", ["TEAM","Fresno State"]),
    ("https://hawaiiathletics.com/sports/football/news",    "https://hawaiiathletics.com",     ["TEAM","Hawai'i"]),
]

# --- Fantasy (NFL) ---
FANTASY_NFL = [
    google_news_feed('site:nbcsports.com "fantasy football" OR "NBC Sports Edge"', "Fantasy NFL"),
    google_news_feed('site:rotowire.com NFL fantasy news', "Fantasy NFL"),
    google_news_feed('site:fantasypros.com NFL player news', "Fantasy NFL"),
    google_news_feed('site:profootballtalk.nbcsports.com injury OR questionable OR doubtful', "Fantasy NFL"),
    google_news_feed('site:espn.com "fantasy football" news', "Fantasy NFL"),
    google_news_feed('site:underdognetwork.com NFL news OR injuries', "Fantasy NFL"),
]

# --- Betting / Props (NFL) ---
BETTING_NFL = [
    google_news_feed('site:actionnetwork.com NFL odds OR picks OR props', "Betting NFL"),
    google_news_feed('site:covers.com NFL injuries OR odds OR picks', "Betting NFL"),
    google_news_feed('site:oddsshark.com NFL odds OR props', "Betting NFL"),
    google_news_feed('site:vegasinsider.com NFL odds OR injuries', "Betting NFL"),
    google_news_feed('site:rotogrinders.com NFL news OR projections', "Betting NFL"),
]

# --- Fantasy (College Football) ---
FANTASY_CFB = [
    google_news_feed('site:rotowire.com college football fantasy', "Fantasy CFB"),
    google_news_feed('site:fantasypros.com college football', "Fantasy CFB"),
    google_news_feed('site:nbcsports.com college football fantasy', "Fantasy CFB"),
]

# --- Betting / Props (College Football) ---
BETTING_CFB = [
    google_news_feed('site:actionnetwork.com college football odds OR picks OR props', "Betting CFB"),
    google_news_feed('site:covers.com college football injuries OR odds OR picks', "Betting CFB"),
    google_news_feed('site:oddsshark.com college football odds OR props', "Betting CFB"),
    google_news_feed('site:vegasinsider.com college football odds OR injuries', "Betting CFB"),
]

REDDIT_FANTASY = [
    ("https://www.reddit.com/r/fantasyfootball/.rss", "https://www.reddit.com", ["Reddit","Fantasy","NFL"]),
    ("https://www.reddit.com/r/CollegeFantasyFootball/.rss", "https://www.reddit.com", ["Reddit","Fantasy","CFB"]),
]


import httpx

def discover_rss(base: str) -> str | None:
    """
    Try a handful of common RSS endpoints on a team site and return the first that looks valid.
    """
    candidates = [
        "/rss/news", "/rss", "/rss.xml",
        "/news/rss", "/news/feed", "/feed", "/feed.xml",
        "/rss/team-news", "/media/rss", "/rss/feeds/news",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 DelphiEdgeScraper/1.0",
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    }
    with httpx.Client(timeout=8.0, follow_redirects=True, headers=headers) as client:
        for path in candidates:
            url = base.rstrip("/") + path
            try:
                r = client.get(url)
                if r.status_code == 200:
                    ct = (r.headers.get("content-type") or "").lower()
                    txt = r.text.lstrip()
                    if ("xml" in ct or "rss" in ct or txt.startswith("<?xml")) and "<rss" in txt[:2000].lower():
                        return url
            except Exception:
                continue
    return None

# --- Yahoo Sports Feeds ---
YAHOO_NFL = "https://sports.yahoo.com/nfl/rss.xml"
YAHOO_CFB = "https://sports.yahoo.com/college-football/rss.xml"

# --- Local / Beat Writer feeds via Google News ---
LOCAL_NEWS = [
    google_news_feed("New Orleans Saints football", "TEAM Saints"),
    google_news_feed("Atlanta Falcons football", "TEAM Falcons"),
    google_news_feed("Tampa Bay Buccaneers football", "TEAM Buccaneers"),
    google_news_feed("Baltimore Ravens football", "TEAM Ravens"),
    google_news_feed("New England Patriots football", "TEAM Patriots"),
    google_news_feed("Buffalo Bills football", "TEAM Bills"),
    google_news_feed("Arizona Cardinals football", "TEAM Cardinals"),
    google_news_feed("Atlanta Falcons football", "TEAM Falcons"),
    google_news_feed("Baltimore Ravens football", "TEAM Ravens"),
    google_news_feed("Buffalo Bills football", "TEAM Bills"),
    google_news_feed("Carolina Panthers football", "TEAM Panthers"),
    google_news_feed("Chicago Bears football", "TEAM Bears"),
    google_news_feed("Cincinnati Bengals football", "TEAM Bengals"),
    google_news_feed("Cleveland Browns football", "TEAM Browns"),
    google_news_feed("Dallas Cowboys football", "TEAM Cowboys"),
    google_news_feed("Denver Broncos football", "TEAM Broncos"),
    google_news_feed("Detroit Lions football", "TEAM Lions"),
    google_news_feed("Green Bay Packers football", "TEAM Packers"),
    google_news_feed("Houston Texans football", "TEAM Texans"),
    google_news_feed("Indianapolis Colts football", "TEAM Colts"),
    google_news_feed("Jacksonville Jaguars football", "TEAM Jaguars"),
    google_news_feed("Kansas City Chiefs football", "TEAM Chiefs"),
    google_news_feed("Las Vegas Raiders football", "TEAM Raiders"),
    google_news_feed("Los Angeles Chargers football", "TEAM Chargers"),
    google_news_feed("Los Angeles Rams football", "TEAM Rams"),
    google_news_feed("Miami Dolphins football", "TEAM Dolphins"),
    google_news_feed("Minnesota Vikings football", "TEAM Vikings"),
    google_news_feed("New England Patriots football", "TEAM Patriots"),
    google_news_feed("New Orleans Saints football", "TEAM Saints"),
    google_news_feed("New York Giants football", "TEAM Giants"),
    google_news_feed("New York Jets football", "TEAM Jets"),
    google_news_feed("Philadelphia Eagles football", "TEAM Eagles"),
    google_news_feed("Pittsburgh Steelers football", "TEAM Steelers"),
    google_news_feed("San Francisco 49ers football", "TEAM 49ers"),
    google_news_feed("Seattle Seahawks football", "TEAM Seahawks"),
    google_news_feed("Tampa Bay Buccaneers football", "TEAM Buccaneers"),
    google_news_feed("Tennessee Titans football", "TEAM Titans"),
    google_news_feed("Washington Commanders football", "TEAM Commanders"),
]


    # SEC Examples
    google_news_feed("Alabama Crimson Tide football", "TEAM Alabama"),
    google_news_feed("Georgia Bulldogs football", "TEAM Georgia"),
    google_news_feed("LSU Tigers football", "TEAM LSU"),
    google_news_feed("South Carolina Gamecocks football", "TEAM South Carolina"),
    google_news_feed("Florida Gators football", "TEAM Florida"),
    google_news_feed("Arkansas Razorbacks football", "TEAM Arkansas"),
    google_news_feed("Auburn Tigers football", "TEAM Auburn"),
    google_news_feed("Ole Miss Rebels football", "TEAM Ole Miss"),
    google_news_feed("Mississippi State Bulldogs football", "TEAM Mississippi State"),
    google_news_feed("Tennessee Volunteers football", "TEAM Tennessee"),
    google_news_feed("Kentucky Wildcats football", "TEAM Kentucky"),
    google_news_feed("Vanderbilt Commodores football", "TEAM Vanderbilt"),
    google_news_feed("Missouri Tigers football", "TEAM Missouri"),
    google_news_feed("Texas Longhorns football", "TEAM Texas"),
    google_news_feed("Oklahoma Sooners football", "TEAM Oklahoma"),

    # Big Ten Examples
    google_news_feed("Michigan Wolverines football", "TEAM Michigan"),
    google_news_feed("Ohio State Buckeyes football", "TEAM Ohio State"),
    google_news_feed("Penn State Nittany Lions football", "TEAM Penn State"),
    google_news_feed("Wisconsin Badgers football", "TEAM Wisconsin"),
    google_news_feed("Michigan Wolverines football", "TEAM Michigan"),
    google_news_feed("Ohio State Buckeyes football", "TEAM Ohio State"),
    google_news_feed("Penn State Nittany Lions football", "TEAM Penn State"),
    google_news_feed("Wisconsin Badgers football", "TEAM Wisconsin"),
    google_news_feed("Iowa Hawkeyes football", "TEAM Iowa"),
    google_news_feed("Minnesota Golden Gophers football", "TEAM Minnesota"),
    google_news_feed("Nebraska Cornhuskers football", "TEAM Nebraska"),
    google_news_feed("Illinois Fighting Illini football", "TEAM Illinois"),
    google_news_feed("Indiana Hoosiers football", "TEAM Indiana"),
    google_news_feed("Michigan State Spartans football", "TEAM Michigan State"),
    google_news_feed("Northwestern Wildcats football", "TEAM Northwestern"),
    google_news_feed("Maryland Terrapins football", "TEAM Maryland"),
    google_news_feed("Rutgers Scarlet Knights football", "TEAM Rutgers"),
    google_news_feed("USC Trojans football", "TEAM USC"),
    google_news_feed("UCLA Bruins football", "TEAM UCLA"),
    google_news_feed("Oregon Ducks football", "TEAM Oregon"),
    google_news_feed("Washington Huskies football", "TEAM Washington"),
]




# ------------------ Main -----------------------
def main():
    print(">>> Starting DelphiEdge scraper...")
    init_db()
    items: list[Article] = []

    with open("feeds.json", "r", encoding="utf-8") as f:
        feeds = json.load(f)

    # ESPN & Reddit (football only)
    items += rss_to_articles(ESPN_NFL, "https://www.espn.com", ["ESPN","NFL"])
    items += rss_to_articles(ESPN_CFB, "https://www.espn.com", ["ESPN","CFB"])
    items += rss_to_articles(R_CFB, "https://www.reddit.com", ["Reddit","CFB"])

    # NFL team news (RSS)
    for feed_url, source, tags in NFL_TEAM_FEEDS:
        items += rss_to_articles(feed_url, source, tags)

    # Ingest every feed listed in feeds.json (RSS-only, super reliable)
    for feed in feeds:
        items += rss_to_articles(
            feed_url=feed["url"],
            source=feed["source"],
            default_tags=feed.get("tags")
        )

    # SEC schools (HTML archives) - Fixed indentation and structure
    for url, source, sel, tags, allow_list, deny_list in SEC_ARCHIVES:
        scraped = scrape_links(url, source, sel, tags, allow_list, deny_list)
        items += scraped

    for url, source, sel, tags in BIG10_ARCHIVES:
        items += scrape_links(url, source, sel, tags)

    for url, source, tags in BIG12_ARCHIVES:
        items += scrape_sidearm(url, source, tags)

    for url, source, tags in ACC_ARCHIVES:
        items += scrape_sidearm(url, source, tags)

    for url, source, tags in PAC_ARCHIVES:
        items += scrape_sidearm(url, source, tags)

    for url, source, tags in MWC_ARCHIVES:
        items += scrape_sidearm(url, source, tags)

    for url, source, tags in LOCAL_NEWS:
        items += scrape_rss(url, source, tags)

    for url, source, tags in LOCAL_NEWS:
        items += rss_to_articles(url, source, tags)

    for url, source, tags in FANTASY_NFL + BETTING_NFL + FANTASY_CFB + BETTING_CFB:
        items += rss_to_articles(url, source, tags)

# (optional)
    for url, source, tags in REDDIT_FANTASY:
        items += rss_to_articles(url, source, tags)





    # Florida via RSS (recommended)
    items += rss_to_articles(
        "https://floridagators.com/rss.aspx?path=football",
        "https://floridagators.com",
        ["TEAM","Florida"]
    )

        # Yahoo Sports
    items += rss_to_articles(YAHOO_NFL, "https://sports.yahoo.com", ["Yahoo","NFL"])
    items += rss_to_articles(YAHOO_CFB, "https://sports.yahoo.com", ["Yahoo","CFB"])

    # Log + ingest Reddit feeds from feeds.json (team subs, r/NFL, r/CFBAnalysis, etc.)
extra_feeds = load_feeds_json()
reddit_feeds = [f for f in extra_feeds if "reddit.com" in (f.get("url","").lower())]
if reddit_feeds:
    items += ingest_feeds_with_logging(reddit_feeds, label_prefix="Reddit")


    if not items:
        print(">>> No items found")
        return

    upsert(items)
    export_csv()
    print(f">>> DONE. Saved {len(items)} items to {DB_PATH} and {CSV_PATH}")

if __name__ == "__main__":
    main()
