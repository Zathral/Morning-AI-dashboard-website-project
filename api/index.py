import os, json, asyncio, re
from datetime import datetime, timedelta, timezone
from typing import Optional, List

import feedparser
import yfinance as yf
import httpx
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mangum import Mangum

try:
    from supabase import create_client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Morning Brief API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY   = os.environ.get("SUPABASE_ANON_KEY", "")

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

# ── Data sources ──────────────────────────────────────────────────────────────
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

WATCHLIST_PRESETS = {
    "mag7":   [("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),
               ("AMZN","Amazon"),("GOOGL","Alphabet"),("META","Meta"),("TSLA","Tesla")],
    "sti":    [("D05.SI","DBS"),("O39.SI","OCBC"),("U11.SI","UOB"),
               ("Z74.SI","Singtel"),("C6L.SI","SIA")],
    "crypto": [("BTC-USD","Bitcoin"),("ETH-USD","Ethereum"),("SOL-USD","Solana")],
}

# Flat name lookup from all presets + core symbols
_NAME_MAP: dict = {s: k for k, s in MARKET_SYMBOLS.items()}
for _grp in WATCHLIST_PRESETS.values():
    for _sym, _name in _grp:
        _NAME_MAP[_sym] = _name

DEFAULT_WATCHLIST = ["AAPL","MSFT","NVDA","AMZN","TSLA","BTC-USD"]

# ── Cache helpers ─────────────────────────────────────────────────────────────
async def cache_get(key: str) -> Optional[dict]:
    if not supabase:
        return None
    try:
        r = supabase.table("cache").select("data,expires_at").eq("key", key).single().execute()
        if r.data:
            exp = datetime.fromisoformat(r.data["expires_at"].replace("Z","+00:00"))
            if exp > datetime.now(timezone.utc):
                return r.data["data"]
    except Exception:
        pass
    return None

async def cache_set(key: str, data: dict, ttl_minutes: int = 15):
    if not supabase:
        return
    try:
        exp = (datetime.utcnow() + timedelta(minutes=ttl_minutes)).isoformat() + "Z"
        supabase.table("cache").upsert({"key": key, "data": data, "expires_at": exp}).execute()
    except Exception:
        pass

# ── Helpers ───────────────────────────────────────────────────────────────────
def score_to_label(score: int) -> str:
    if score < 20: return "Extreme Fear"
    if score < 40: return "Fear"
    if score < 60: return "Neutral"
    if score < 80: return "Greed"
    return "Extreme Greed"

async def _fetch_articles() -> list:
    articles = []
    for fd in RSS_FEEDS:
        try:
            feed = feedparser.parse(fd["url"])
            for entry in feed.entries[:3]:
                title = entry.get("title","").strip()
                if not title:
                    continue
                raw = entry.get("summary","")
                summary = re.sub(r"<[^>]+>","",raw)[:280].strip()
                articles.append({
                    "title":    title,
                    "summary":  summary,
                    "link":     entry.get("link",""),
                    "published":entry.get("published",""),
                    "category": fd["category"],
                })
        except Exception:
            continue
    return articles

async def _fetch_ticker(symbol: str) -> dict:
    """Fetch price + sparkline for a single ticker."""
    try:
        hist = yf.Ticker(symbol).history(period="5d", interval="1d")
        if len(hist) >= 2:
            cur  = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            chg  = (cur - prev) / prev * 100
            return {
                "name":       _NAME_MAP.get(symbol, symbol),
                "price":      round(cur, 2),
                "change_pct": round(chg, 2),
                "sparkline":  [round(float(v),2) for v in hist["Close"].tolist()],
                "up":         chg >= 0,
            }
    except Exception:
        pass
    return {"name": _NAME_MAP.get(symbol, symbol), "price": None,
            "change_pct": 0, "sparkline": [], "up": True}

async def save_daily_snapshot(market_data: dict, score: int, sentiment: str,
                               top_theme: str, key_entities: list, bullets: list):
    """Store today's data into Supabase for historical tracking (once per day)."""
    if not supabase:
        return
    today = datetime.utcnow().date().isoformat()
    try:
        # Check if snapshot already saved today
        existing = supabase.table("sentiment_history") \
            .select("snapshot_date").eq("snapshot_date", today).execute()
        if existing.data:
            return  # already saved today

        # Market history rows
        for name, md in market_data.get("market", {}).items():
            if md.get("price"):
                supabase.table("market_history").upsert({
                    "snapshot_date": today,
                    "symbol":        md["symbol"],
                    "name":          name,
                    "price":         md["price"],
                    "change_pct":    md["change_pct"],
                }).execute()

        # Sentiment snapshot
        supabase.table("sentiment_history").upsert({
            "snapshot_date": today,
            "score":         score,
            "label":         score_to_label(score),
            "sentiment":     sentiment,
            "top_theme":     top_theme,
            "key_entities":  key_entities,
            "bullets":       bullets,
        }).execute()
    except Exception:
        pass

async def get_rag_context() -> str:
    """Build last-7-day context string for the chatbot."""
    if not supabase:
        return ""
    try:
        sent_rows = (supabase.table("sentiment_history")
            .select("*").order("snapshot_date", desc=True).limit(7).execute()).data or []
        mkt_rows = (supabase.table("market_history")
            .select("*")
            .in_("symbol",["^GSPC","^IXIC","BTC-USD","^STI"])
            .order("snapshot_date", desc=True).limit(28).execute()).data or []
        if not sent_rows:
            return ""
        lines = ["=== HISTORICAL DATA (last 7 days) ==="]
        for row in reversed(sent_rows):
            d  = row["snapshot_date"]
            lbl = row.get("label") or score_to_label(row.get("score",50))
            lines.append(f"\n[{d}] Sentiment: {lbl} ({row.get('score','?')}/100) | Theme: {row.get('top_theme','—')}")
            day_mkt = [m for m in mkt_rows if m["snapshot_date"] == d]
            if day_mkt:
                mstr = ", ".join(f"{m['name']} {m['change_pct']:+.1f}%" for m in day_mkt if m.get("change_pct") is not None)
                lines.append(f"  Markets: {mstr}")
        return "\n".join(lines)
    except Exception:
        return ""

# ── V1 Endpoints ──────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status":"ok","version":"2.0","gemini":bool(GEMINI_API_KEY),
            "supabase":supabase is not None,"timestamp":datetime.utcnow().isoformat()}

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

    cur = data.get("current", {})
    hrly = data.get("hourly", {})
    dly = data.get("daily", {})

    # SAFE FIX: Next 8 hours using datetime comparison
    now = datetime.now()
    hourly_forecast = []
    
    for i, t in enumerate(hrly.get("time", [])):
        # Parse the time string (Open-Meteo returns ISO format)
        forecast_time = datetime.fromisoformat(t)
        
        # Show future hours (including current hour if within 30 mins)
        time_diff = (forecast_time - now).total_seconds() / 3600
        
        if time_diff >= -0.5 and len(hourly_forecast) < 8:  # -0.5 = within last 30 mins
            hourly_forecast.append({
                "time": t,
                "temp": hrly["temperature_2m"][i],
                "rain_prob": hrly["precipitation_probability"][i],
                "weather_code": hrly["weather_code"][i],
            })

    # Ensure we always have at least 8 items (pad with next day's data if needed)
    # This prevents the brief endpoint from breaking
    if len(hourly_forecast) < 8 and len(hrly.get("time", [])) > len(hourly_forecast):
        # Add more hours from the same data
        remaining = min(8 - len(hourly_forecast), len(hrly.get("time", [])) - len(hourly_forecast))
        for i in range(len(hourly_forecast), len(hourly_forecast) + remaining):
            if i < len(hrly.get("time", [])):
                hourly_forecast.append({
                    "time": hrly["time"][i],
                    "temp": hrly["temperature_2m"][i],
                    "rain_prob": hrly["precipitation_probability"][i],
                    "weather_code": hrly["weather_code"][i],
                })

    result = {
        "current": {
            "temperature": cur.get("temperature_2m"),
            "feels_like": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"),
            "weather_code": cur.get("weather_code"),
            "wind_speed": cur.get("wind_speed_10m"),
        },
        "daily": {
            "max_temp": (dly.get("temperature_2m_max") or [None])[0],
            "min_temp": (dly.get("temperature_2m_min") or [None])[0],
            "rain_prob": (dly.get("precipitation_probability_max") or [None])[0],
            "sunrise": (dly.get("sunrise") or [None])[0],
            "sunset": (dly.get("sunset") or [None])[0],
        },
        "hourly": hourly_forecast,  # Always at least 8 items
    }
    await cache_set("weather", result, ttl_minutes=30)
    return result

@app.get("/api/market")
async def get_market():
    cached = await cache_get("market")
    if cached: return cached
    market: dict = {}
    for name, symbol in MARKET_SYMBOLS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d")
            if len(hist) >= 2:
                cur  = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                chg  = (cur - prev) / prev * 100
                market[name] = {"symbol":symbol,"price":round(cur,2),"change_pct":round(chg,2),
                                "sparkline":[round(float(v),2) for v in hist["Close"].tolist()],
                                "up":chg>=0}
            else:
                market[name] = {"symbol":symbol,"price":None,"change_pct":0,"sparkline":[],"up":True}
        except Exception as e:
            market[name] = {"symbol":symbol,"price":None,"change_pct":0,"sparkline":[],"up":True,"error":str(e)}
    result = {"market": market}
    await cache_set("market", result, 5)
    return result

@app.get("/api/brief")
async def get_brief(name: str = "Jeremy"):
    cached = await cache_get("brief")
    if cached: return cached
    articles, weather_data, market_data = await asyncio.gather(
        _fetch_articles(), get_weather(), get_market()
    )
    if not GEMINI_API_KEY:
        result = {"brief":f"Good morning, {name}. Set GEMINI_API_KEY to enable AI briefs.",
                  "news_summary":{"bullets":[a["title"] for a in articles[:5]],
                                  "sentiment":"neutral","top_theme":"—","key_entities":[]},
                  "articles":articles[:8],"timestamp":datetime.utcnow().isoformat()}
        return result
    headlines = "\n".join(f"- [{a['category'].upper()}] {a['title']}" for a in articles[:12])
    mkt_lines = [f"{n}: {md['price']} ({'▲' if md['up'] else '▼'}{abs(md['change_pct'])}%)"
                 for n, md in market_data.get("market",{}).items() if md.get("price")]
    mkt_text  = "  |  ".join(mkt_lines) or "N/A"
    wc = weather_data.get("current",{})
    wd = weather_data.get("daily",{})
    wx_text = (f"{wc.get('temperature')}°C (feels {wc.get('feels_like')}°C), "
               f"humidity {wc.get('humidity')}%, rain {wd.get('rain_prob')}%")
    hour = datetime.now().hour
    greeting = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    prompt = f"""You are a concise morning briefing AI for a student in Singapore.
Return ONLY a valid JSON object — no markdown, no backticks:
{{
  "brief": "Start 'Good {greeting}, {name}.'. 3 sentences: market insight with number, key news, weather/tip.",
  "bullets": ["5 crisp one-sentence news bullets across categories"],
  "sentiment": "bullish|bearish|neutral|cautious",
  "top_theme": "Dominant theme in 6-9 words",
  "key_entities": ["3-5 notable companies/people/places"]
}}
MARKETS: {mkt_text}
WEATHER: {wx_text}
HEADLINES:\n{headlines}"""
    try:
        model    = genai.GenerativeModel("gemini-1.5-flash")
        text     = model.generate_content(prompt).text.strip()
        text     = re.sub(r"^```[a-z]*\n?","",text).rstrip("```").strip()
        parsed   = json.loads(text)
    except Exception:
        parsed = {"brief":f"Good {greeting}, {name}. {mkt_lines[0]+'.' if mkt_lines else 'Markets active.'}",
                  "bullets":[a["title"] for a in articles[:5]],
                  "sentiment":"neutral","top_theme":"Global news","key_entities":[]}
    result = {
        "brief": parsed.get("brief",""),
        "news_summary":{"bullets":parsed.get("bullets",[]),"sentiment":parsed.get("sentiment","neutral"),
                        "top_theme":parsed.get("top_theme",""),"key_entities":parsed.get("key_entities",[])},
        "articles": articles[:8],
        "timestamp": datetime.utcnow().isoformat(),
    }
    await cache_set("brief", result, 30)
    # Auto-save daily snapshot (non-blocking, best effort)
    sent_map = {"bullish":70,"bearish":25,"cautious":35,"neutral":50}
    score = sent_map.get(parsed.get("sentiment","neutral"), 50)
    await save_daily_snapshot(
        market_data, score, parsed.get("sentiment","neutral"),
        parsed.get("top_theme",""), parsed.get("key_entities",[]), parsed.get("bullets",[])
    )
    return result

# ── V2 Endpoints ──────────────────────────────────────────────────────────────

@app.get("/api/watchlist-data")
async def get_watchlist_data(tickers: str = "AAPL,MSFT,NVDA,AMZN,TSLA,BTC-USD"):
    """Fetch live price data for a comma-separated list of ticker symbols."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:24]
    cache_key   = "wl_" + "_".join(sorted(ticker_list))[:90]
    cached      = await cache_get(cache_key)
    if cached:   return cached
    results = await asyncio.gather(*[_fetch_ticker(sym) for sym in ticker_list])
    data    = {sym: res for sym, res in zip(ticker_list, results)}
    result  = {"data": data}
    await cache_set(cache_key, result, 3)
    return result

@app.get("/api/watchlist/{session_key}")
async def load_watchlist(session_key: str):
    """Load a saved watchlist from Supabase by session key."""
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
    """Persist watchlist to Supabase."""
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

@app.get("/api/sentiment")
async def get_sentiment():
    """Deep sentiment analysis: 0-100 fear/greed score + category breakdown + entity heatmap."""
    cached = await cache_get("sentiment_v2")
    if cached: return cached

    articles, market_data = await asyncio.gather(_fetch_articles(), get_market())
    mkt     = market_data.get("market", {})
    up_ct   = sum(1 for md in mkt.values() if md.get("up"))
    mkt_str = " | ".join(f"{n}: {'▲' if md.get('up') else '▼'}{abs(md.get('change_pct',0))}%"
                          for n, md in mkt.items() if md.get("price"))
    base_score = int((up_ct / max(len(mkt), 1)) * 100)

    if not GEMINI_API_KEY:
        result = {"score":base_score,"label":score_to_label(base_score),"categories":{},"entities":[]}
        await cache_set("sentiment_v2", result, 30)
        return result

    headlines = "\n".join(f"- [{a['category'].upper()}] {a['title']}" for a in articles[:15])
    prompt = f"""Analyze market sentiment. Return ONLY valid JSON, no markdown:
{{
  "score": <integer 0-100, 0=extreme fear, 50=neutral, 100=extreme greed>,
  "categories": {{
    "finance":   {{"score":<0-100>,"sentiment":"bullish|bearish|neutral"}},
    "tech":      {{"score":<0-100>,"sentiment":"bullish|bearish|neutral"}},
    "global":    {{"score":<0-100>,"sentiment":"bullish|bearish|neutral"}},
    "singapore": {{"score":<0-100>,"sentiment":"bullish|bearish|neutral"}}
  }},
  "entities": [{{"name":"...","sentiment":"positive|negative|neutral","count":<int>}}]
}}
Entities: top 7 most mentioned companies/assets/people. 
MARKETS: {mkt_str}
HEADLINES:\n{headlines}"""
    try:
        text   = genai.GenerativeModel("gemini-1.5-flash").generate_content(prompt).text.strip()
        text   = re.sub(r"^```[a-z]*\n?","",text).rstrip("```").strip()
        parsed = json.loads(text)
        score  = int(parsed.get("score", base_score))
        result = {"score":score,"label":score_to_label(score),
                  "categories":parsed.get("categories",{}),"entities":parsed.get("entities",[])}
    except Exception:
        result = {"score":base_score,"label":score_to_label(base_score),"categories":{},"entities":[]}
    await cache_set("sentiment_v2", result, 30)
    return result

@app.get("/api/history")
async def get_history(symbol: str = "^GSPC", days: int = 30):
    """Historical price data (yfinance) with sentiment overlay (Supabase)."""
    days = max(7, min(days, 365))
    cache_key = f"hist_{symbol}_{days}"
    cached    = await cache_get(cache_key)
    if cached: return cached

    period_map = {7:"10d", 30:"1mo", 90:"3mo", 180:"6mo", 365:"1y"}
    period = next((v for k, v in period_map.items() if days <= k), "1y")

    try:
        hist = yf.Ticker(symbol).history(period=period, interval="1d")
        prices = [{"date":idx.strftime("%Y-%m-%d"),"price":round(float(row["Close"]),2)}
                  for idx, row in hist.iterrows()]
    except Exception as e:
        return {"symbol":symbol,"prices":[],"sentiment":[],"stats":{},"error":str(e)}

    if len(prices) < 2:
        return {"symbol":symbol,"prices":[],"sentiment":[],"stats":{}}

    vals   = [p["price"] for p in prices]
    stats  = {"start":vals[0],"current":vals[-1],
               "change_pct":round((vals[-1]-vals[0])/vals[0]*100,2),
               "high":round(max(vals),2),"low":round(min(vals),2)}

    sentiment_data = []
    if supabase:
        try:
            from_date = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
            rows = supabase.table("sentiment_history") \
                     .select("snapshot_date,score,label") \
                     .gte("snapshot_date", from_date) \
                     .order("snapshot_date").execute().data or []
            sentiment_data = [{"date":r["snapshot_date"],"score":r["score"],"label":r.get("label","")} for r in rows]
        except Exception:
            pass

    result = {"symbol":symbol,"name":_NAME_MAP.get(symbol,symbol),
              "prices":prices,"sentiment":sentiment_data,"stats":stats}
    await cache_set(cache_key, result, 10)
    return result

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """RAG chatbot: answers using today's data + stored history as context."""
    if not GEMINI_API_KEY:
        return {"response":"GEMINI_API_KEY not configured.","sources":[]}

    # --- Build context ---
    today_context, sources = "", []
    brief_cache = await cache_get("brief")
    if brief_cache:
        ns  = brief_cache.get("news_summary", {})
        mkt = brief_cache.get("market", {})
        art = brief_cache.get("articles", [])
        mkt_str  = ", ".join(f"{n}:{md['price']}({'▲' if md.get('up') else '▼'}{abs(md.get('change_pct',0))}%)"
                              for n, md in (mkt or {}).items() if md.get("price"))
        bullets  = "\n".join(f"- {b}" for b in ns.get("bullets",[]))
        hl       = "\n".join(f"- [{a.get('category','?').upper()}] {a.get('title','')}" for a in art[:10])
        today_context = (f"=== TODAY ===\nMarkets: {mkt_str}\n"
                         f"Sentiment: {ns.get('sentiment','?')} | Theme: {ns.get('top_theme','?')}\n"
                         f"Summary:\n{bullets}\nHeadlines:\n{hl}")
        sources.append("Today's data")

    history_context = await get_rag_context()
    if history_context:
        sources.append("Historical records")

    # --- Build Gemini message history ---
    # Inject context as a seeded exchange at the start
    gem_history = []
    if today_context or history_context:
        ctx = "\n\n".join(filter(None, [today_context, history_context]))
        gem_history = [
            {"role":"user",  "parts":[f"Here is my current context data:\n\n{ctx}\n\nPlease use this to answer my questions accurately."]},
            {"role":"model", "parts":["Got it. I have access to today's market data, news summaries, and historical sentiment records. Ask me anything."]}
        ]
    for msg in req.history[-8:]:
        role = "user" if msg.role == "user" else "model"
        gem_history.append({"role":role,"parts":[msg.content]})

    try:
        model    = genai.GenerativeModel(
            "gemini-1.5-flash",
            system_instruction=(
                "You are a sharp, concise financial AI assistant for a student in Singapore. "
                "Be specific with numbers. Keep answers to 2-4 sentences unless a list is clearly better. "
                "If the answer isn't in your context, say so honestly."
            ),
        )
        session  = model.start_chat(history=gem_history)
        response = session.send_message(req.message)
        answer   = response.text.strip()
    except Exception as e:
        answer = f"Sorry, I ran into an issue: {str(e)[:120]}"

    return {"response": answer, "sources": sources}

@app.get("/api/presets")
async def get_presets():
    """Return preset watchlist groups (used by frontend to populate tabs)."""
    return {"presets": {group: [{"symbol":s,"name":n} for s,n in items]
                         for group, items in WATCHLIST_PRESETS.items()},
            "defaults": DEFAULT_WATCHLIST}

# ── Vercel entry point ────────────────────────────────────────────────────────
handler = Mangum(app, lifespan="off")
