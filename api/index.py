import os, json, asyncio, re
from datetime import datetime, timedelta, timezone
from typing import Optional, List

import feedparser
import yfinance as yf
import httpx
import google.generativeai as genai
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mangum import Mangum

try:
    from supabase import create_client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Morning Brief API", version="3.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["GET","POST","PUT"], allow_headers=["*"])

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY   = os.environ.get("SUPABASE_ANON_KEY", "")

# Singapore timezone (UTC+8) — used throughout for correct local time comparisons
SGT = timezone(timedelta(hours=8))

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

supabase = None
if SUPABASE_AVAILABLE and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        pass

# ── Pydantic models ───────────────────────────────────────────────────────────
class WatchlistUpdate(BaseModel):
    tickers: List[str]

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []

# ── Gemini helpers ────────────────────────────────────────────────────────────
_GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash"]

def _get_model_name() -> str:
    return _GEMINI_MODELS[0]

def _generate_sync(prompt: str, model_name: str = None) -> str:
    """Run Gemini synchronously — call via asyncio.to_thread to avoid blocking."""
    name = model_name or _get_model_name()
    for attempt_name in [name] + [m for m in _GEMINI_MODELS if m != name]:
        try:
            return genai.GenerativeModel(attempt_name).generate_content(prompt).text
        except Exception as e:
            if "not found" in str(e).lower() or "404" in str(e):
                continue
            raise
    raise RuntimeError("All Gemini models failed")

async def _generate(prompt: str, timeout: float = 30.0) -> str:
    """Async wrapper for Gemini with timeout. Safe for serverless."""
    return await asyncio.wait_for(
        asyncio.to_thread(_generate_sync, prompt),
        timeout=timeout
    )

def _chat_sync(model_name: str, system: str, history: list, message: str) -> str:
    for attempt in [model_name] + [m for m in _GEMINI_MODELS if m != model_name]:
        try:
            m = genai.GenerativeModel(attempt, system_instruction=system)
            return m.start_chat(history=history).send_message(message).text.strip()
        except Exception as e:
            if "not found" in str(e).lower() or "404" in str(e):
                continue
            raise
    raise RuntimeError("All chat models failed")

# ── RSS feeds ─────────────────────────────────────────────────────────────────
RSS_FEEDS = [
    {"url": "http://feeds.bbci.co.uk/news/world/rss.xml",            "category": "world"},
    {"url": "https://feeds.reuters.com/reuters/worldNews",           "category": "world"},
    {"url": "https://www.channelnewsasia.com/rss/8395986",           "category": "singapore"},
    {"url": "https://www.channelnewsasia.com/rss/8395984",           "category": "singapore"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "category": "finance"},
    {"url": "https://feeds.reuters.com/reuters/businessNews",        "category": "finance"},
    {"url": "http://feeds.bbci.co.uk/news/business/rss.xml",         "category": "finance"},
    {"url": "https://techcrunch.com/feed/",                          "category": "tech"},
]

# ── Market symbols ────────────────────────────────────────────────────────────
MARKET_SYMBOLS = {
    "S&P 500": "^GSPC", "NASDAQ": "^IXIC", "STI": "^STI",
    "Bitcoin": "BTC-USD", "Gold": "GC=F", "Oil": "CL=F",
}
WATCHLIST_PRESETS = {
    "mag7":    [("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),
                ("AMZN","Amazon"),("GOOGL","Alphabet"),("META","Meta"),("TSLA","Tesla")],
    "sti":     [("D05.SI","DBS"),("O39.SI","OCBC"),("U11.SI","UOB"),
                ("Z74.SI","Singtel"),("C6L.SI","SIA")],
    "crypto":  [("BTC-USD","Bitcoin"),("ETH-USD","Ethereum"),("SOL-USD","Solana")],
    "sectors": [("XLK","Tech ETF"),("XLV","Healthcare ETF"),("XLF","Financials ETF"),
                ("XLE","Energy ETF"),("SMH","Semiconductors"),("XBI","Biotech")],
}
DEFAULT_WATCHLIST = ["^GSPC","^IXIC","^STI","BTC-USD","GC=F","CL=F","AAPL","NVDA","MSFT"]

_NAME_MAP: dict = {s: k for k, s in MARKET_SYMBOLS.items()}
for _grp in WATCHLIST_PRESETS.values():
    for _sym, _name in _grp:
        _NAME_MAP[_sym] = _name

# ── Supabase cache ────────────────────────────────────────────────────────────
async def cache_get(key: str) -> Optional[dict]:
    if not supabase: return None
    try:
        def _get():
            return supabase.table("cache").select("data,expires_at").eq("key", key).single().execute()
        r = await asyncio.wait_for(asyncio.to_thread(_get), timeout=3.0)
        if r.data:
            exp = datetime.fromisoformat(r.data["expires_at"].replace("Z", "+00:00"))
            if exp > datetime.now(timezone.utc):
                return r.data["data"]
    except Exception:
        pass
    return None

async def cache_set(key: str, data: dict, ttl: int = 15):
    if not supabase: return
    try:
        exp = (datetime.utcnow() + timedelta(minutes=ttl)).isoformat() + "Z"
        def _set():
            supabase.table("cache").upsert({"key": key, "data": data, "expires_at": exp}).execute()
        await asyncio.wait_for(asyncio.to_thread(_set), timeout=3.0)
    except Exception:
        pass

# ── Utility helpers ───────────────────────────────────────────────────────────
def score_to_label(s: int) -> str:
    if s < 20: return "Extreme Fear"
    if s < 40: return "Fear"
    if s < 60: return "Neutral"
    if s < 80: return "Greed"
    return "Extreme Greed"

async def _fetch_articles() -> list:
    """
    Fetch RSS feeds concurrently, each with a 5s timeout.
    Any feed that times out or errors is silently skipped.
    """
    async def _one_feed(fd: dict) -> list:
        try:
            feed = await asyncio.wait_for(
                asyncio.to_thread(feedparser.parse, fd["url"]),
                timeout=5.0
            )
            items = []
            for entry in feed.entries[:4]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:300].strip()
                items.append({
                    "title":     title,
                    "summary":   summary,
                    "link":      entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "category":  fd["category"],
                })
            return items
        except Exception:
            return []

    results = await asyncio.gather(*[_one_feed(fd) for fd in RSS_FEEDS])
    return [item for batch in results for item in batch]

async def _fetch_ticker(symbol: str) -> dict:
    """Fetch single ticker with 9s timeout."""
    try:
        hist = await asyncio.wait_for(
            asyncio.to_thread(yf.Ticker(symbol).history, period="5d", interval="1d"),
            timeout=9.0
        )
        if len(hist) >= 2:
            cur, prev = float(hist["Close"].iloc[-1]), float(hist["Close"].iloc[-2])
            chg = (cur - prev) / prev * 100
            return {"name": _NAME_MAP.get(symbol, symbol), "price": round(cur, 2),
                    "change_pct": round(chg, 2),
                    "sparkline": [round(float(v), 2) for v in hist["Close"].tolist()],
                    "up": chg >= 0}
        elif len(hist) == 1:
            cur = float(hist["Close"].iloc[0])
            return {"name": _NAME_MAP.get(symbol, symbol), "price": round(cur, 2),
                    "change_pct": 0.0, "sparkline": [round(cur, 2)], "up": True}
    except Exception:
        pass
    return {"name": _NAME_MAP.get(symbol, symbol), "price": None,
            "change_pct": 0, "sparkline": [], "up": True}

async def save_daily_snapshot(market_data: dict, score: int, sentiment: str,
                               top_theme: str, key_entities: list, bullets: list):
    if not supabase:
        return
    today = datetime.now(SGT).date().isoformat()
    try:
        existing = supabase.table("sentiment_history").select("snapshot_date") \
                       .eq("snapshot_date", today).execute()
        if existing.data:
            return
        for name, md in market_data.get("market", {}).items():
            if md.get("price"):
                supabase.table("market_history").upsert({
                    "snapshot_date": today, "symbol": md["symbol"],
                    "name": name, "price": md["price"], "change_pct": md["change_pct"],
                }).execute()
        supabase.table("sentiment_history").upsert({
            "snapshot_date": today, "score": score, "label": score_to_label(score),
            "sentiment": sentiment, "top_theme": top_theme,
            "key_entities": key_entities, "bullets": bullets,
        }).execute()
    except Exception:
        pass

async def get_rag_context() -> str:
    if not supabase:
        return ""
    try:
        sent = (supabase.table("sentiment_history").select("*")
                .order("snapshot_date", desc=True).limit(7).execute()).data or []
        mkt  = (supabase.table("market_history").select("*")
                .in_("symbol", ["^GSPC","^IXIC","BTC-USD","^STI"])
                .order("snapshot_date", desc=True).limit(28).execute()).data or []
        if not sent:
            return ""
        lines = ["=== HISTORICAL DATA (last 7 days) ==="]
        for row in reversed(sent):
            d   = row["snapshot_date"]
            lbl = row.get("label") or score_to_label(row.get("score", 50))
            lines.append(f"\n[{d}] Sentiment: {lbl} ({row.get('score','?')}/100) | Theme: {row.get('top_theme','—')}")
            dm = [m for m in mkt if m["snapshot_date"] == d]
            if dm:
                lines.append("  Markets: " + ", ".join(
                    f"{m['name']} {m['change_pct']:+.1f}%" for m in dm
                    if m.get("change_pct") is not None))
        return "\n".join(lines)
    except Exception:
        return ""

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.1",
            "gemini": bool(GEMINI_API_KEY), "supabase": supabase is not None,
            "timestamp": datetime.now(SGT).isoformat()}

@app.get("/api/weather")
async def get_weather():
    cached = await cache_get("weather_v3")
    if cached:
        return cached

    lat, lon = 1.3521, 103.8198
    wx_url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature"
        "&hourly=temperature_2m,precipitation_probability,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,sunrise,sunset"
        "&timezone=Asia%2FSingapore&forecast_days=1"
    )
    aq_url = (
        f"https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lon}"
        "&current=pm2_5,us_aqi&timezone=Asia%2FSingapore"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        wx_resp, aq_resp = await asyncio.gather(
            client.get(wx_url), client.get(aq_url), return_exceptions=True
        )

    data   = wx_resp.json()   if not isinstance(wx_resp,  Exception) else {}
    aqdata = aq_resp.json()   if not isinstance(aq_resp,  Exception) else {}

    cur  = data.get("current", {})
    hrly = data.get("hourly",  {})
    dly  = data.get("daily",   {})

    # ── FIX: use Singapore local time (UTC+8) when finding the current hour ──
    # Open-Meteo returns times in SGT (we requested timezone=Asia/Singapore).
    # datetime.now() on Vercel is UTC; comparing UTC hour to SGT hours was
    # causing the forecast to start 8 hours in the past.
    now_sgt = datetime.now(SGT).strftime("%Y-%m-%dT%H:00")

    hourly_fc, started, count = [], False, 0
    for i, t in enumerate(hrly.get("time", [])):
        if t >= now_sgt:
            started = True
        if started and count < 8:
            hourly_fc.append({
                "time":         t,
                "temp":         hrly["temperature_2m"][i],
                "rain_prob":    hrly["precipitation_probability"][i],
                "weather_code": hrly["weather_code"][i],
            })
            count += 1

    aq_cur    = aqdata.get("current", {})
    us_aqi    = aq_cur.get("us_aqi")
    aqi_label = ("Good" if (us_aqi or 0) < 51 else
                 "Moderate" if (us_aqi or 0) < 101 else
                 "Unhealthy (Sensitive)" if (us_aqi or 0) < 151 else "Unhealthy")

    result = {
        "current": {
            "temperature":  cur.get("temperature_2m"),
            "feels_like":   cur.get("apparent_temperature"),
            "humidity":     cur.get("relative_humidity_2m"),
            "weather_code": cur.get("weather_code"),
            "wind_speed":   cur.get("wind_speed_10m"),
        },
        "daily": {
            "max_temp":  (dly.get("temperature_2m_max")              or [None])[0],
            "min_temp":  (dly.get("temperature_2m_min")              or [None])[0],
            "rain_prob": (dly.get("precipitation_probability_max")   or [None])[0],
            "sunrise":   (dly.get("sunrise")                         or [None])[0],
            "sunset":    (dly.get("sunset")                          or [None])[0],
        },
        "hourly": hourly_fc,
        "air_quality": {
            "pm2_5": round(aq_cur["pm2_5"], 1) if aq_cur.get("pm2_5") else None,
            "us_aqi": us_aqi,
            "label":  aqi_label,
        },
    }
    await cache_set("weather_v3", result, ttl=30)
    return result

@app.get("/api/watchlist-data")
async def get_watchlist_data(tickers: str = ",".join(DEFAULT_WATCHLIST)):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:28]
    cache_key   = "wl3_" + "_".join(sorted(ticker_list))[:90]
    cached      = await cache_get(cache_key)
    if cached:
        return cached
    results = await asyncio.gather(*[_fetch_ticker(s) for s in ticker_list], return_exceptions=True)
    data = {sym: (res if not isinstance(res, Exception)
                  else {"name": _NAME_MAP.get(sym,sym), "price": None,
                        "change_pct": 0, "sparkline": [], "up": True})
            for sym, res in zip(ticker_list, results)}
    result = {"data": data}
    await cache_set(cache_key, result, ttl=3)
    return result

@app.get("/api/watchlist/{session_key}")
async def load_watchlist(session_key: str):
    if not supabase:
        return {"tickers": DEFAULT_WATCHLIST}
    try:
        r = supabase.table("watchlist").select("tickers") \
              .eq("session_key", session_key).single().execute()
        if r.data:
            return {"tickers": r.data["tickers"]}
    except Exception:
        pass
    return {"tickers": DEFAULT_WATCHLIST}

@app.put("/api/watchlist/{session_key}")
async def save_watchlist(session_key: str, body: WatchlistUpdate):
    if supabase:
        try:
            supabase.table("watchlist").upsert({
                "session_key": session_key,
                "tickers":     body.tickers,
                "updated_at":  datetime.utcnow().isoformat() + "Z",
            }).execute()
        except Exception:
            pass
    return {"ok": True}

@app.get("/api/market")
async def get_market():
    cached = await cache_get("market_v3")
    if cached:
        return cached
    results = await asyncio.gather(*[_fetch_ticker(s) for s in MARKET_SYMBOLS.values()],
                                   return_exceptions=True)
    market = {}
    for (name, symbol), res in zip(MARKET_SYMBOLS.items(), results):
        d = res if not isinstance(res, Exception) else \
            {"name": name, "price": None, "change_pct": 0, "sparkline": [], "up": True}
        d["symbol"] = symbol
        market[name] = d
    result = {"market": market}
    await cache_set("market_v3", result, ttl=5)
    return result

async def cached_or_fetch(cache_key: str, fetcher, fallback: dict, timeout: float = 12.0) -> dict:
    cached = await cache_get(cache_key)
    if cached:
        return cached
    try:
        return await asyncio.wait_for(fetcher(), timeout=timeout)
    except Exception:
        return fallback

@app.get("/api/brief")
async def get_brief(name: str = "Jeremy"):
    cached = await cache_get("brief_v3")
    if cached:
        return cached

    # Fetch articles, weather, and market concurrently. Cache is preferred, but
    # cold starts still need live data so the first load does not get stuck with
    # empty context.
    articles, market_data, weather_data = await asyncio.gather(
        _fetch_articles(),
        cached_or_fetch("market_v3", get_market, {"market": {}}, timeout=12.0),
        cached_or_fetch("weather_v3", get_weather, {}, timeout=12.0),
    )

    if not GEMINI_API_KEY:
        result = {
            "brief": f"Good morning, {name}. Set GEMINI_API_KEY to enable AI briefs.",
            "weather_tip": "Check the weather before heading out.",
            "news_summary": {"bullets": {"world":[], "singapore":[], "finance":[]},
                             "sentiment": "neutral", "top_theme": "—", "key_entities": []},
            "articles": articles[:12], "timestamp": datetime.now(SGT).isoformat(),
        }
        return result

    # Build context strings
    headlines_by_cat: dict = {"world":[], "singapore":[], "finance":[], "tech":[]}
    for a in articles[:20]:
        cat = a["category"]
        if cat in headlines_by_cat and len(headlines_by_cat[cat]) < 5:
            headlines_by_cat[cat].append(a["title"])
    hl_text = "\n".join(f"[{cat.upper()}] {t}"
                         for cat, titles in headlines_by_cat.items() for t in titles)

    mkt_lines = [
        f"{n}: {md['price']} ({'▲' if md['up'] else '▼'}{abs(md['change_pct'])}%)"
        for n, md in market_data.get("market", {}).items() if md.get("price")
    ]
    mkt_text = " | ".join(mkt_lines[:6]) or "N/A"

    wc = weather_data.get("current", {})
    wd = weather_data.get("daily",   {})
    aq = weather_data.get("air_quality", {})
    wx_text = (f"{wc.get('temperature')}°C feels {wc.get('feels_like')}°C, "
               f"rain {wd.get('rain_prob')}%, high {wd.get('max_temp')}°C, "
               f"AQI {aq.get('us_aqi','?')} ({aq.get('label','?')})")

    hour = datetime.now(SGT).hour
    greeting = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"

    prompt = f"""You are a sharp morning briefing AI for someone in Singapore.
Return ONLY a valid JSON object — no markdown, no backticks, no extra text.

{{
  "brief": "4-6 sentences. Start 'Good {greeting}, {name}.'. Include: (1) biggest market story with exact numbers and sector/company names; (2) two significant world or Singapore news stories with specific details — never vague; (3) practical Singapore weather tip.",
  "weather_tip": "One concise practical tip for today's Singapore weather — umbrella timing, heat, or air quality note.",
  "bullets": {{
    "world":     ["3 crisp bullets on top world news with specific names and details"],
    "singapore": ["3 crisp bullets on Singapore-specific news"],
    "finance":   ["3 crisp bullets on market-moving company or sector news with numbers"]
  }},
  "sentiment":    "bullish|bearish|neutral|cautious",
  "top_theme":    "Dominant theme across all news in 6-9 words",
  "key_entities": ["4-6 most prominent companies, people, or places today"]
}}

MARKETS: {mkt_text}
WEATHER: {wx_text}
HEADLINES:\n{hl_text}"""

    try:
        # Run Gemini in a thread pool with a 30s timeout so it never blocks the event loop
        text   = await _generate(prompt, timeout=30.0)
        text   = re.sub(r"^```[a-z]*\n?", "", text).rstrip("```").strip()
        parsed = json.loads(text)
    except Exception:
        bullets_fb = {
            "world":     [a["title"] for a in articles if a["category"] == "world"][:3],
            "singapore": [a["title"] for a in articles if a["category"] == "singapore"][:3],
            "finance":   [a["title"] for a in articles if a["category"] == "finance"][:3],
        }
        parsed = {
            "brief":        f"Good {greeting}, {name}. {mkt_lines[0]+'.' if mkt_lines else 'Markets are active.'}",
            "weather_tip":  "Check the weather before heading out.",
            "bullets":      bullets_fb,
            "sentiment":    "neutral",
            "top_theme":    "Global markets and news",
            "key_entities": [],
        }

    result = {
        "brief":       parsed.get("brief", ""),
        "weather_tip": parsed.get("weather_tip", ""),
        "news_summary": {
            "bullets":      parsed.get("bullets", {"world":[],"singapore":[],"finance":[]}),
            "sentiment":    parsed.get("sentiment", "neutral"),
            "top_theme":    parsed.get("top_theme", ""),
            "key_entities": parsed.get("key_entities", []),
        },
        "articles":  articles[:16],
        "timestamp": datetime.now(SGT).isoformat(),
    }
    await cache_set("brief_v3", result, ttl=30)

    # Save daily snapshot (uses SGT date)
    sent_map = {"bullish": 70, "bearish": 25, "cautious": 35, "neutral": 50}
    score = sent_map.get(parsed.get("sentiment", "neutral"), 50)
    flat_bullets = [b for cat in parsed.get("bullets", {}).values()
                    for b in (cat if isinstance(cat, list) else [])]
    await save_daily_snapshot(market_data, score, parsed.get("sentiment","neutral"),
                               parsed.get("top_theme",""), parsed.get("key_entities",[]), flat_bullets)
    return result

@app.get("/api/sentiment")
async def get_sentiment():
    cached = await cache_get("sentiment_v3")
    if cached:
        return cached

    articles, market_data = await asyncio.gather(_fetch_articles(), get_market())
    mkt = market_data.get("market", {})
    up_ct  = sum(1 for md in mkt.values() if md.get("up"))
    mkt_str = " | ".join(f"{n}: {'▲' if md.get('up') else '▼'}{abs(md.get('change_pct',0))}%"
                          for n, md in mkt.items() if md.get("price"))
    base = int((up_ct / max(len(mkt), 1)) * 100)

    if not GEMINI_API_KEY:
        result = {"score": base, "label": score_to_label(base), "categories": {}, "entities": []}
        await cache_set("sentiment_v3", result, ttl=30)
        return result

    headlines = "\n".join(f"- [{a['category'].upper()}] {a['title']}" for a in articles[:18])
    prompt = f"""Analyse market sentiment. Return ONLY valid JSON, no markdown:
{{
  "categories": {{
    "tech":        {{"score":<0-100>,"sentiment":"bullish|bearish|neutral"}},
    "healthcare":  {{"score":<0-100>,"sentiment":"bullish|bearish|neutral"}},
    "finance":     {{"score":<0-100>,"sentiment":"bullish|bearish|neutral"}},
    "commodities": {{"score":<0-100>,"sentiment":"bullish|bearish|neutral"}}
  }},
  "entities": [{{"name":"...","sentiment":"positive|negative|neutral","count":<int>}}]
}}
Score 0=extreme fear, 50=neutral, 100=extreme greed. Entities: top 8.
MARKETS: {mkt_str}
HEADLINES:\n{headlines}"""

    try:
        text   = await _generate(prompt, timeout=25.0)
        text   = re.sub(r"^```[a-z]*\n?","",text).rstrip("```").strip()
        parsed = json.loads(text)
        cats   = parsed.get("categories", {})
        scores = [v.get("score", 50) for v in cats.values() if isinstance(v, dict)]
        score  = int(sum(scores) / len(scores)) if scores else base
        result = {"score": score, "label": score_to_label(score),
                  "categories": cats, "entities": parsed.get("entities", [])}
    except Exception:
        result = {"score": base, "label": score_to_label(base), "categories": {}, "entities": []}

    await cache_set("sentiment_v3", result, ttl=30)
    return result

@app.get("/api/trends")
async def get_trends():
    cached = await cache_get("trends_v3")
    if cached:
        return cached

    articles = await _fetch_articles()
    if not GEMINI_API_KEY or not articles:
        return {"topics": [], "timestamp": datetime.now(SGT).isoformat()}

    headlines = "\n".join(f"- {a['title']}" for a in articles[:30])
    prompt = f"""Analyse these news headlines for recurring topics. Return ONLY valid JSON:
{{
  "topics": [
    {{"topic":"...","count":<headlines mentioning this>,"pct":<% of {len(articles)} total>,"category":"finance|tech|geopolitics|singapore|commodities|other","sentiment":"positive|negative|neutral"}}
  ]
}}
List top 8 topics that appear in at least 2 headlines.
HEADLINES:\n{headlines}"""

    try:
        text   = await _generate(prompt, timeout=20.0)
        text   = re.sub(r"^```[a-z]*\n?","",text).rstrip("```").strip()
        parsed = json.loads(text)
        result = {"topics": parsed.get("topics", []), "timestamp": datetime.now(SGT).isoformat()}
    except Exception:
        result = {"topics": [], "timestamp": datetime.now(SGT).isoformat()}

    await cache_set("trends_v3", result, ttl=30)
    return result

@app.get("/api/history")
async def get_history(symbol: str = "^GSPC", days: int = 30):
    days = max(7, min(days, 365))
    cache_key = f"hist3_{symbol}_{days}"
    cached    = await cache_get(cache_key)
    if cached:
        return cached

    period_map = {7:"10d", 30:"1mo", 90:"3mo", 180:"6mo", 365:"1y"}
    period = next((v for k, v in period_map.items() if days <= k), "1y")

    try:
        hist = await asyncio.wait_for(
            asyncio.to_thread(yf.Ticker(symbol).history, period=period, interval="1d"),
            timeout=15.0
        )
        if hist.empty:
            return {"symbol": symbol, "prices": [], "sentiment": [], "stats": {},
                    "error": "No data — Yahoo Finance may be temporarily unavailable."}
        prices = [{"date": idx.strftime("%Y-%m-%d"), "price": round(float(row["Close"]), 2)}
                  for idx, row in hist.iterrows()]
    except asyncio.TimeoutError:
        return {"symbol": symbol, "prices": [], "sentiment": [], "stats": {},
                "error": "Request timed out fetching price data."}
    except Exception as e:
        return {"symbol": symbol, "prices": [], "sentiment": [], "stats": {}, "error": str(e)}

    if len(prices) < 2:
        return {"symbol": symbol, "prices": prices, "sentiment": [], "stats": {}}

    vals  = [p["price"] for p in prices]
    stats = {"start": vals[0], "current": vals[-1],
              "change_pct": round((vals[-1]-vals[0])/vals[0]*100, 2),
              "high": round(max(vals), 2), "low": round(min(vals), 2)}

    sentiment_data = []
    if supabase:
        try:
            from_date = (datetime.now(SGT) - timedelta(days=days)).date().isoformat()
            rows = (supabase.table("sentiment_history")
                    .select("snapshot_date,score,label")
                    .gte("snapshot_date", from_date)
                    .order("snapshot_date").execute()).data or []
            sentiment_data = [{"date": r["snapshot_date"], "score": r["score"],
                                "label": r.get("label","")} for r in rows]
        except Exception:
            pass

    result = {"symbol": symbol, "name": _NAME_MAP.get(symbol, symbol),
              "prices": prices, "sentiment": sentiment_data, "stats": stats}
    await cache_set(cache_key, result, ttl=10)
    return result

@app.get("/api/stock-insights")
async def get_stock_insights(tickers: str = "AAPL,NVDA,TSLA"):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:8]
    cache_key   = "ins3_" + "_".join(sorted(ticker_list))[:80]
    cached      = await cache_get(cache_key)
    if cached:
        return cached
    if not GEMINI_API_KEY:
        return {"insights": {t: "" for t in ticker_list}}

    brief_cache = await cache_get("brief_v3")
    hl = "\n".join(a.get("title","") for a in (brief_cache or {}).get("articles",[])[:20])

    prompt = f"""For each stock, one sentence on what's relevant in today's news (or blank string if nothing).
Return ONLY valid JSON: {{"insights":{{{", ".join(f'"{t}":"..."' for t in ticker_list)}}}}}
TODAY'S HEADLINES:\n{hl}"""

    try:
        text   = await _generate(prompt, timeout=20.0)
        text   = re.sub(r"^```[a-z]*\n?","",text).rstrip("```").strip()
        parsed = json.loads(text)
        result = {"insights": parsed.get("insights", {})}
    except Exception:
        result = {"insights": {t: "" for t in ticker_list}}

    await cache_set(cache_key, result, ttl=30)
    return result

@app.get("/api/presets")
async def get_presets():
    return {"presets": {g: [{"symbol":s,"name":n} for s,n in items]
                         for g, items in WATCHLIST_PRESETS.items()},
            "defaults": DEFAULT_WATCHLIST}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not GEMINI_API_KEY:
        return {"response": "GEMINI_API_KEY not configured.", "sources": []}

    today_context, sources = "", []
    brief_cache = await cache_get("brief_v3")
    if brief_cache:
        ns  = brief_cache.get("news_summary", {})
        art = brief_cache.get("articles", [])
        mkt_str = " | ".join(
            f"{n}:{md['price']}({'▲' if md.get('up') else '▼'}{abs(md.get('change_pct',0))}%)"
            for n, md in (brief_cache.get("market") or {}).items() if md.get("price")
        )
        bullets_obj = ns.get("bullets", {})
        bullets_flat = [b for cat in bullets_obj.values()
                        for b in (cat if isinstance(cat, list) else [])]
        hl = "\n".join(f"- [{a.get('category','?').upper()}] {a.get('title','')}" for a in art[:14])
        today_context = (f"=== TODAY (SGT) ===\nMarkets: {mkt_str}\n"
                         f"Sentiment: {ns.get('sentiment','?')} | Theme: {ns.get('top_theme','?')}\n"
                         f"Key points:\n" + "\n".join(f"- {b}" for b in bullets_flat) +
                         f"\nHeadlines:\n{hl}")
        sources.append("Today's data")

    history_context = await get_rag_context()
    if history_context:
        sources.append("Historical records")

    gem_history = []
    if today_context or history_context:
        ctx = "\n\n".join(filter(None, [today_context, history_context]))
        gem_history = [
            {"role": "user",  "parts": [f"Here is my context:\n\n{ctx}"]},
            {"role": "model", "parts": ["Understood. I have today's market data, news, and historical context. Ask away."]}
        ]
    for msg in req.history[-8:]:
        gem_history.append({"role": "user" if msg.role == "user" else "model",
                             "parts": [msg.content]})

    system = ("Sharp, concise financial assistant for a Singapore user. "
              "Be specific with numbers. 2-4 sentences unless a list is better. "
              "If the answer isn't in the context, say so honestly.")
    try:
        answer = await asyncio.wait_for(
            asyncio.to_thread(_chat_sync, _get_model_name(), system, gem_history, req.message),
            timeout=28.0
        )
    except Exception as e:
        answer = f"Sorry, I ran into an issue: {str(e)[:120]}"

    return {"response": answer, "sources": sources}

handler = Mangum(app, lifespan="off")
