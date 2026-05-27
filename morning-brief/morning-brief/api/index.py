import os
import json
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser
import yfinance as yf
import httpx
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

try:
    from supabase import create_client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# ─── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="Morning Brief API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ─── Config ───────────────────────────────────────────────────────────────────

GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
SUPABASE_URL    = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY    = os.environ.get("SUPABASE_ANON_KEY", "")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

supabase = None
if SUPABASE_AVAILABLE and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        pass

# ─── Data Sources ─────────────────────────────────────────────────────────────

RSS_FEEDS = [
    {"url": "http://feeds.bbci.co.uk/news/world/rss.xml",            "category": "global"},
    {"url": "http://feeds.bbci.co.uk/news/business/rss.xml",         "category": "finance"},
    {"url": "https://www.channelnewsasia.com/rss/8395986",           "category": "singapore"},
    {"url": "https://techcrunch.com/feed/",                          "category": "tech"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "category": "finance"},
]

MARKET_SYMBOLS = {
    "S&P 500": "^GSPC",
    "NASDAQ":  "^IXIC",
    "STI":     "^STI",
    "Bitcoin": "BTC-USD",
    "Gold":    "GC=F",
    "Oil":     "CL=F",
}

# ─── Supabase Cache Helpers ───────────────────────────────────────────────────

async def cache_get(key: str) -> Optional[dict]:
    if not supabase:
        return None
    try:
        result = (
            supabase.table("cache")
            .select("data, expires_at")
            .eq("key", key)
            .single()
            .execute()
        )
        if result.data:
            expires_at = datetime.fromisoformat(
                result.data["expires_at"].replace("Z", "+00:00")
            )
            if expires_at > datetime.now(timezone.utc):
                return result.data["data"]
    except Exception:
        pass
    return None


async def cache_set(key: str, data: dict, ttl_minutes: int = 15):
    if not supabase:
        return
    try:
        expires_at = (
            datetime.utcnow() + timedelta(minutes=ttl_minutes)
        ).isoformat() + "Z"
        supabase.table("cache").upsert(
            {"key": key, "data": data, "expires_at": expires_at}
        ).execute()
    except Exception:
        pass

# ─── Internal Helpers ─────────────────────────────────────────────────────────

async def _fetch_articles() -> list:
    """Fetch and clean articles from all RSS feeds."""
    articles = []
    for feed_def in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_def["url"])
            for entry in feed.entries[:3]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                raw = entry.get("summary", "")
                summary = re.sub(r"<[^>]+>", "", raw)[:280].strip()
                articles.append({
                    "title":     title,
                    "summary":   summary,
                    "link":      entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "category":  feed_def["category"],
                })
        except Exception:
            continue
    return articles

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status":    "ok",
        "gemini":    bool(GEMINI_API_KEY),
        "supabase":  supabase is not None,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/weather")
async def get_weather():
    cached = await cache_get("weather")
    if cached:
        return cached

    lat, lon = 1.3521, 103.8198  # Singapore
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,weather_code,"
        "wind_speed_10m,apparent_temperature"
        "&hourly=temperature_2m,precipitation_probability,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,sunrise,sunset"
        "&timezone=Asia%2FSingapore&forecast_days=1"
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        data = resp.json()

    cur  = data.get("current", {})
    hrly = data.get("hourly", {})
    dly  = data.get("daily", {})

    # Next 8 hours from now
    now_str = datetime.now().strftime("%Y-%m-%dT%H:00")
    hourly_forecast, started, count = [], False, 0
    for i, t in enumerate(hrly.get("time", [])):
        if t >= now_str:
            started = True
        if started and count < 8:
            hourly_forecast.append({
                "time":         t,
                "temp":         hrly["temperature_2m"][i],
                "rain_prob":    hrly["precipitation_probability"][i],
                "weather_code": hrly["weather_code"][i],
            })
            count += 1

    result = {
        "current": {
            "temperature":  cur.get("temperature_2m"),
            "feels_like":   cur.get("apparent_temperature"),
            "humidity":     cur.get("relative_humidity_2m"),
            "weather_code": cur.get("weather_code"),
            "wind_speed":   cur.get("wind_speed_10m"),
        },
        "daily": {
            "max_temp":  (dly.get("temperature_2m_max")  or [None])[0],
            "min_temp":  (dly.get("temperature_2m_min")  or [None])[0],
            "rain_prob": (dly.get("precipitation_probability_max") or [None])[0],
            "sunrise":   (dly.get("sunrise")  or [None])[0],
            "sunset":    (dly.get("sunset")   or [None])[0],
        },
        "hourly": hourly_forecast,
    }
    await cache_set("weather", result, ttl_minutes=30)
    return result


@app.get("/api/market")
async def get_market():
    cached = await cache_get("market")
    if cached:
        return cached

    market: dict = {}
    for name, symbol in MARKET_SYMBOLS.items():
        try:
            ticker = yf.Ticker(symbol)
            hist   = ticker.history(period="5d", interval="1d")
            if len(hist) >= 2:
                cur_p  = float(hist["Close"].iloc[-1])
                prev_p = float(hist["Close"].iloc[-2])
                chg    = (cur_p - prev_p) / prev_p * 100
                market[name] = {
                    "symbol":     symbol,
                    "price":      round(cur_p, 2),
                    "change_pct": round(chg, 2),
                    "sparkline":  [round(float(v), 2) for v in hist["Close"].tolist()],
                    "up":         chg >= 0,
                }
            else:
                market[name] = {
                    "symbol": symbol, "price": None,
                    "change_pct": 0, "sparkline": [], "up": True,
                }
        except Exception as e:
            market[name] = {
                "symbol": symbol, "price": None,
                "change_pct": 0, "sparkline": [], "up": True, "error": str(e),
            }

    result = {"market": market}
    await cache_set("market", result, ttl_minutes=5)
    return result


@app.get("/api/brief")
async def get_brief(name: str = "Jeremy"):
    """
    Primary endpoint. Returns AI morning brief + news bullets + sentiment.
    Weather and market load in parallel from the frontend.
    """
    cached = await cache_get("brief")
    if cached:
        return cached

    # Fetch articles, weather, and market concurrently for brief context
    articles, weather_data, market_data = await asyncio.gather(
        _fetch_articles(),
        get_weather(),
        get_market(),
    )

    if not GEMINI_API_KEY:
        result = {
            "brief": (
                f"Good morning, {name}. Set GEMINI_API_KEY in your environment "
                "to enable AI-generated briefs."
            ),
            "news_summary": {
                "bullets":      [a["title"] for a in articles[:5]],
                "sentiment":    "neutral",
                "top_theme":    "—",
                "key_entities": [],
            },
            "articles":  articles[:8],
            "timestamp": datetime.utcnow().isoformat(),
        }
        return result

    # Build context strings for Gemini
    headlines = "\n".join(
        f"- [{a['category'].upper()}] {a['title']}" for a in articles[:12]
    )

    mkt_lines = []
    for mname, md in market_data.get("market", {}).items():
        if md.get("price"):
            arrow = "▲" if md["up"] else "▼"
            mkt_lines.append(
                f"{mname}: {md['price']} ({arrow}{abs(md['change_pct'])}%)"
            )
    mkt_text = "  |  ".join(mkt_lines) or "Market data unavailable"

    wc = weather_data.get("current", {})
    wd = weather_data.get("daily", {})
    wx_text = (
        f"{wc.get('temperature')}°C (feels {wc.get('feels_like')}°C), "
        f"humidity {wc.get('humidity')}%, "
        f"rain {wd.get('rain_prob')}%, "
        f"high {wd.get('max_temp')}°C / low {wd.get('min_temp')}°C"
    )

    hour = datetime.now().hour
    greeting = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"

    prompt = f"""You are a sharp, concise morning briefing AI for a student in Singapore.

Return ONLY a valid JSON object — no markdown, no backticks, no extra text:
{{
  "brief": "Start with 'Good {greeting}, {name}.'. Exactly 3 sentences: one market insight with a specific number, one key news item, one weather/practical tip for Singapore today.",
  "bullets": ["5 crisp one-sentence bullets covering the most important headlines across categories"],
  "sentiment": "bullish|bearish|neutral|cautious",
  "top_theme": "Dominant theme across all news today in 6-9 words",
  "key_entities": ["3-5 notable companies, people, or places in today's news"]
}}

MARKETS TODAY: {mkt_text}
WEATHER (SG): {wx_text}
HEADLINES:
{headlines}"""

    try:
        model    = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        text     = response.text.strip()
        # Strip any accidental markdown fences
        text     = re.sub(r"^```[a-z]*\n?", "", text).rstrip("```").strip()
        parsed   = json.loads(text)
    except Exception:
        parsed = {
            "brief": (
                f"Good {greeting}, {name}. "
                f"{mkt_lines[0] + '.' if mkt_lines else 'Markets are active today.'} "
                f"{'High rain probability — keep an umbrella handy.' if (wd.get('rain_prob') or 0) > 50 else 'Looks like a clear day ahead.'}"
            ),
            "bullets":      [a["title"] for a in articles[:5]],
            "sentiment":    "neutral",
            "top_theme":    "Global markets and news",
            "key_entities": [],
        }

    result = {
        "brief": parsed.get("brief", ""),
        "news_summary": {
            "bullets":      parsed.get("bullets", []),
            "sentiment":    parsed.get("sentiment", "neutral"),
            "top_theme":    parsed.get("top_theme", ""),
            "key_entities": parsed.get("key_entities", []),
        },
        "articles":  articles[:8],
        "timestamp": datetime.utcnow().isoformat(),
    }
    await cache_set("brief", result, ttl_minutes=30)
    return result


# ─── Vercel ASGI entry point ──────────────────────────────────────────────────
handler = Mangum(app, lifespan="off")
