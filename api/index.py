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
app = FastAPI(title="Morning Brief API", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["GET","POST","PUT"], allow_headers=["*"])

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

def _model():
    """Return a fresh Gemini model instance. Uses 2.0-flash, falls back to 1.5-flash."""
    for name in ("gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash"):
        try:
            return genai.GenerativeModel(name)
        except Exception:
            continue
    return genai.GenerativeModel("gemini-1.5-flash")

# ── Pydantic models ───────────────────────────────────────────────────────────
class WatchlistUpdate(BaseModel):
    tickers: List[str]

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []

# ── RSS feeds ─────────────────────────────────────────────────────────────────
RSS_FEEDS = [
    # World
    {"url": "http://feeds.bbci.co.uk/news/world/rss.xml",             "category": "world"},
    {"url": "https://feeds.reuters.com/reuters/worldNews",            "category": "world"},
    # Singapore
    {"url": "https://www.channelnewsasia.com/rss/8395986",            "category": "singapore"},
    {"url": "https://www.channelnewsasia.com/rss/8395984",            "category": "singapore"},
    # Finance / Markets / Companies
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",  "category": "finance"},
    {"url": "https://feeds.reuters.com/reuters/businessNews",         "category": "finance"},
    {"url": "http://feeds.bbci.co.uk/news/business/rss.xml",          "category": "finance"},
    # Tech / AI
    {"url": "https://techcrunch.com/feed/",                           "category": "tech"},
]

# ── Market symbols ────────────────────────────────────────────────────────────
MARKET_SYMBOLS = {
    "S&P 500": "^GSPC", "NASDAQ": "^IXIC", "STI": "^STI",
    "Bitcoin": "BTC-USD", "Gold": "GC=F", "Oil": "CL=F",
}

WATCHLIST_PRESETS = {
    "mag7":   [("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),
               ("AMZN","Amazon"),("GOOGL","Alphabet"),("META","Meta"),("TSLA","Tesla")],
    "sti":    [("D05.SI","DBS"),("O39.SI","OCBC"),("U11.SI","UOB"),
               ("Z74.SI","Singtel"),("C6L.SI","SIA")],
    "crypto": [("BTC-USD","Bitcoin"),("ETH-USD","Ethereum"),("SOL-USD","Solana")],
    "sectors":[ ("XLK","Tech ETF"),("XLV","Healthcare ETF"),
                ("XLF","Financials ETF"),("XLE","Energy ETF"),
                ("SMH","Semiconductors"),("XBI","Biotech") ],
}
DEFAULT_WATCHLIST = ["^GSPC","^IXIC","^STI","BTC-USD","GC=F","CL=F","AAPL","NVDA","MSFT"]

_NAME_MAP: dict = {s: k for k, s in MARKET_SYMBOLS.items()}
for _grp in WATCHLIST_PRESETS.values():
    for _sym, _name in _grp:
        _NAME_MAP[_sym] = _name

# ── Cache helpers ─────────────────────────────────────────────────────────────
async def cache_get(key: str) -> Optional[dict]:
    if not supabase: return None
    try:
        r = supabase.table("cache").select("data,expires_at").eq("key",key).single().execute()
        if r.data:
            exp = datetime.fromisoformat(r.data["expires_at"].replace("Z","+00:00"))
            if exp > datetime.now(timezone.utc):
                return r.data["data"]
    except Exception: pass
    return None

async def cache_set(key: str, data: dict, ttl: int = 15):
    if not supabase: return
    try:
        exp = (datetime.utcnow()+timedelta(minutes=ttl)).isoformat()+"Z"
        supabase.table("cache").upsert({"key":key,"data":data,"expires_at":exp}).execute()
    except Exception: pass

# ── Helpers ───────────────────────────────────────────────────────────────────
def score_to_label(s: int) -> str:
    if s<20: return "Extreme Fear"
    if s<40: return "Fear"
    if s<60: return "Neutral"
    if s<80: return "Greed"
    return "Extreme Greed"

async def _fetch_articles() -> list:
    articles = []
    for fd in RSS_FEEDS:
        try:
            feed = feedparser.parse(fd["url"])
            for entry in feed.entries[:4]:
                title = entry.get("title","").strip()
                if not title: continue
                summary = re.sub(r"<[^>]+>","",entry.get("summary",""))[:300].strip()
                articles.append({"title":title,"summary":summary,
                                  "link":entry.get("link",""),
                                  "published":entry.get("published",""),
                                  "category":fd["category"]})
        except Exception: continue
    return articles

async def _fetch_ticker(symbol: str) -> dict:
    try:
        hist = await asyncio.wait_for(
            asyncio.to_thread(yf.Ticker(symbol).history, period="5d", interval="1d"),
            timeout=9.0
        )
        if len(hist) >= 2:
            cur, prev = float(hist["Close"].iloc[-1]), float(hist["Close"].iloc[-2])
            chg = (cur-prev)/prev*100
            return {"name":_NAME_MAP.get(symbol,symbol),"price":round(cur,2),
                    "change_pct":round(chg,2),
                    "sparkline":[round(float(v),2) for v in hist["Close"].tolist()],
                    "up":chg>=0}
        elif len(hist)==1:
            cur = float(hist["Close"].iloc[0])
            return {"name":_NAME_MAP.get(symbol,symbol),"price":round(cur,2),
                    "change_pct":0.0,"sparkline":[round(cur,2)],"up":True}
    except Exception: pass
    return {"name":_NAME_MAP.get(symbol,symbol),"price":None,"change_pct":0,"sparkline":[],"up":True}

async def save_daily_snapshot(market_data: dict, score: int, sentiment: str,
                               top_theme: str, key_entities: list, bullets: list):
    if not supabase: return
    today = datetime.utcnow().date().isoformat()
    try:
        existing = supabase.table("sentiment_history").select("snapshot_date").eq("snapshot_date",today).execute()
        if existing.data: return
        for name, md in market_data.get("market",{}).items():
            if md.get("price"):
                supabase.table("market_history").upsert({"snapshot_date":today,"symbol":md["symbol"],
                    "name":name,"price":md["price"],"change_pct":md["change_pct"]}).execute()
        supabase.table("sentiment_history").upsert({"snapshot_date":today,"score":score,
            "label":score_to_label(score),"sentiment":sentiment,"top_theme":top_theme,
            "key_entities":key_entities,"bullets":bullets}).execute()
    except Exception: pass

async def get_rag_context() -> str:
    if not supabase: return ""
    try:
        sent = (supabase.table("sentiment_history").select("*").order("snapshot_date",desc=True).limit(7).execute()).data or []
        mkt  = (supabase.table("market_history").select("*")
                .in_("symbol",["^GSPC","^IXIC","BTC-USD","^STI"])
                .order("snapshot_date",desc=True).limit(28).execute()).data or []
        if not sent: return ""
        lines = ["=== HISTORICAL DATA (last 7 days) ==="]
        for row in reversed(sent):
            d = row["snapshot_date"]
            lbl = row.get("label") or score_to_label(row.get("score",50))
            lines.append(f"\n[{d}] Sentiment: {lbl} ({row.get('score','?')}/100) | Theme: {row.get('top_theme','—')}")
            dm = [m for m in mkt if m["snapshot_date"]==d]
            if dm:
                lines.append("  Markets: "+", ".join(f"{m['name']} {m['change_pct']:+.1f}%" for m in dm if m.get("change_pct") is not None))
        return "\n".join(lines)
    except Exception: return ""

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status":"ok","version":"3.0","gemini":bool(GEMINI_API_KEY),
            "supabase":supabase is not None,"timestamp":datetime.utcnow().isoformat()}

@app.get("/api/weather")
async def get_weather():
    cached = await cache_get("weather_v3")
    if cached: return cached
    lat, lon = 1.3521, 103.8198
    wx_url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
              "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature"
              "&hourly=temperature_2m,precipitation_probability,weather_code"
              "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"
              "&timezone=Asia%2FSingapore&forecast_days=1")
    aq_url  = (f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}"
               "&current=pm2_5,us_aqi&timezone=Asia%2FSingapore")
    async with httpx.AsyncClient(timeout=10.0) as client:
        wx_resp, aq_resp = await asyncio.gather(client.get(wx_url), client.get(aq_url),
                                                return_exceptions=True)
    data  = wx_resp.json() if not isinstance(wx_resp,Exception) else {}
    aqdata= aq_resp.json() if not isinstance(aq_resp,Exception) else {}
    cur  = data.get("current",{})
    hrly = data.get("hourly",{})
    dly  = data.get("daily",{})
    now_str = datetime.now().strftime("%Y-%m-%dT%H:00")
    hourly_fc, started, count = [], False, 0
    for i,t in enumerate(hrly.get("time",[])):
        if t>=now_str: started=True
        if started and count<8:
            hourly_fc.append({"time":t,"temp":hrly["temperature_2m"][i],
                               "rain_prob":hrly["precipitation_probability"][i],
                               "weather_code":hrly["weather_code"][i]})
            count+=1
    aq_cur  = aqdata.get("current",{})
    pm25    = aq_cur.get("pm2_5")
    us_aqi  = aq_cur.get("us_aqi")
    aqi_label = ("Good" if (us_aqi or 0)<51 else "Moderate" if (us_aqi or 0)<101
                 else "Unhealthy for Sensitive Groups" if (us_aqi or 0)<151 else "Unhealthy")
    result = {
        "current":{"temperature":cur.get("temperature_2m"),"feels_like":cur.get("apparent_temperature"),
                   "humidity":cur.get("relative_humidity_2m"),"weather_code":cur.get("weather_code"),
                   "wind_speed":cur.get("wind_speed_10m")},
        "daily":{"max_temp":(dly.get("temperature_2m_max") or [None])[0],
                 "min_temp":(dly.get("temperature_2m_min") or [None])[0],
                 "rain_prob":(dly.get("precipitation_probability_max") or [None])[0],
                 "sunrise":(dly.get("sunrise") or [None])[0],
                 "sunset":(dly.get("sunset") or [None])[0]},
        "hourly": hourly_fc,
        "air_quality":{"pm2_5":round(pm25,1) if pm25 else None,"us_aqi":us_aqi,"label":aqi_label},
    }
    await cache_set("weather_v3", result, 30)
    return result

@app.get("/api/watchlist-data")
async def get_watchlist_data(tickers: str = ",".join(DEFAULT_WATCHLIST)):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:28]
    cache_key   = "wl3_"+"_".join(sorted(ticker_list))[:90]
    cached      = await cache_get(cache_key)
    if cached:   return cached
    results = await asyncio.gather(*[_fetch_ticker(s) for s in ticker_list], return_exceptions=True)
    data = {}
    for sym,res in zip(ticker_list,results):
        data[sym] = res if not isinstance(res,Exception) else \
            {"name":_NAME_MAP.get(sym,sym),"price":None,"change_pct":0,"sparkline":[],"up":True}
    result = {"data":data}
    await cache_set(cache_key, result, 3)
    return result

@app.get("/api/watchlist/{session_key}")
async def load_watchlist(session_key: str):
    if not supabase: return {"tickers":DEFAULT_WATCHLIST}
    try:
        r = supabase.table("watchlist").select("tickers").eq("session_key",session_key).single().execute()
        if r.data: return {"tickers":r.data["tickers"]}
    except Exception: pass
    return {"tickers":DEFAULT_WATCHLIST}

@app.put("/api/watchlist/{session_key}")
async def save_watchlist(session_key: str, body: WatchlistUpdate):
    if supabase:
        try:
            supabase.table("watchlist").upsert({"session_key":session_key,"tickers":body.tickers,
                "updated_at":datetime.utcnow().isoformat()+"Z"}).execute()
        except Exception: pass
    return {"ok":True}

@app.get("/api/brief")
async def get_brief(name: str = "Jeremy"):
    cached = await cache_get("brief_v3")
    if cached: return cached
    articles, weather_data, market_data = await asyncio.gather(
        _fetch_articles(), get_weather(), get_market_internal()
    )
    if not GEMINI_API_KEY:
        result = {"brief":f"Good morning, {name}. Set GEMINI_API_KEY to enable AI briefs.",
                  "weather_tip":"Check local weather before heading out.",
                  "news_summary":{"bullets":{"world":[],"singapore":[],"finance":[]},"sentiment":"neutral",
                                  "top_theme":"—","key_entities":[]},"articles":articles[:12],
                  "timestamp":datetime.utcnow().isoformat()}
        return result
    headlines_by_cat: dict = {"world":[],"singapore":[],"finance":[],"tech":[]}
    for a in articles[:20]:
        cat = a["category"]
        if cat in headlines_by_cat and len(headlines_by_cat[cat])<5:
            headlines_by_cat[cat].append(a["title"])
    hl_text = "\n".join(f"[{cat.upper()}] {t}" for cat,titles in headlines_by_cat.items() for t in titles)
    mkt_lines=[f"{n}: {md['price']} ({'▲' if md['up'] else '▼'}{abs(md['change_pct'])}%)"
               for n,md in market_data.get("market",{}).items() if md.get("price")]
    mkt_text  = " | ".join(mkt_lines[:6]) or "N/A"
    wc = weather_data.get("current",{})
    wd = weather_data.get("daily",{})
    aq = weather_data.get("air_quality",{})
    wx_text = (f"{wc.get('temperature')}°C feels {wc.get('feels_like')}°C, "
               f"rain {wd.get('rain_prob')}%, high {wd.get('max_temp')}°C, AQI {aq.get('us_aqi','?')} ({aq.get('label','?')})")
    hour = datetime.now().hour
    greeting = "morning" if hour<12 else "afternoon" if hour<17 else "evening"
    prompt = f"""You are a sharp morning briefing AI for someone in Singapore.
Return ONLY a valid JSON object — no markdown, no backticks, no extra text.

{{
  "brief": "4-6 sentences. Start 'Good {greeting}, {name}.'. Then: (1) the single biggest market story with exact numbers and sector or company names — be specific, e.g. 'Semiconductor stocks surged, with NVIDIA up 4.2%'; (2) two significant world or Singapore news stories with specific names, countries, or events — never vague; (3) end with a practical Singapore weather tip.",
  "weather_tip": "One concise, practical tip for today's weather in Singapore — e.g. umbrella timing, heat advisory, or air quality note.",
  "bullets": {{
    "world":     ["3 crisp one-sentence bullets on top world news with specific details"],
    "singapore": ["3 crisp one-sentence bullets on Singapore news"],
    "finance":   ["3 crisp one-sentence bullets on market-moving company or sector news with numbers"]
  }},
  "sentiment":    "bullish|bearish|neutral|cautious",
  "top_theme":    "The single dominant theme across all news in 6-9 words",
  "key_entities": ["4-6 companies, people, or places most prominent today"]
}}

MARKETS: {mkt_text}
WEATHER: {wx_text}
HEADLINES:
{hl_text}"""
    try:
        text   = _model().generate_content(prompt).text.strip()
        text   = re.sub(r"^```[a-z]*\n?","",text).rstrip("```").strip()
        parsed = json.loads(text)
    except Exception:
        bullets_fallback = {"world":[a["title"] for a in articles if a["category"]=="world"][:3],
                            "singapore":[a["title"] for a in articles if a["category"]=="singapore"][:3],
                            "finance":[a["title"] for a in articles if a["category"]=="finance"][:3]}
        parsed = {"brief":f"Good {greeting}, {name}. {mkt_lines[0]+'.' if mkt_lines else 'Markets are active.'}",
                  "weather_tip":"Check the weather before heading out.",
                  "bullets":bullets_fallback,"sentiment":"neutral",
                  "top_theme":"Global markets and news","key_entities":[]}
    result = {"brief":parsed.get("brief",""),
              "weather_tip":parsed.get("weather_tip",""),
              "news_summary":{"bullets":parsed.get("bullets",{"world":[],"singapore":[],"finance":[]}),
                              "sentiment":parsed.get("sentiment","neutral"),
                              "top_theme":parsed.get("top_theme",""),
                              "key_entities":parsed.get("key_entities",[])},
              "articles":articles[:16],"timestamp":datetime.utcnow().isoformat()}
    await cache_set("brief_v3", result, 30)
    sent_map = {"bullish":70,"bearish":25,"cautious":35,"neutral":50}
    score = sent_map.get(parsed.get("sentiment","neutral"),50)
    flat_bullets = [b for cat_bulls in parsed.get("bullets",{}).values() for b in cat_bulls]
    await save_daily_snapshot(market_data, score, parsed.get("sentiment","neutral"),
                               parsed.get("top_theme",""), parsed.get("key_entities",[]), flat_bullets)
    return result

async def get_market_internal() -> dict:
    """Used internally — bypasses cache TTL check for brief generation."""
    cached = await cache_get("market_v3")
    if cached: return cached
    return await get_market()

@app.get("/api/market")
async def get_market():
    cached = await cache_get("market_v3")
    if cached: return cached
    market: dict = {}
    for name,symbol in MARKET_SYMBOLS.items():
        market[name] = await _fetch_ticker(symbol)
        market[name]["symbol"] = symbol
    result = {"market":market}
    await cache_set("market_v3", result, 5)
    return result

@app.get("/api/sentiment")
async def get_sentiment():
    cached = await cache_get("sentiment_v3")
    if cached: return cached
    articles, market_data = await asyncio.gather(_fetch_articles(), get_market())
    mkt = market_data.get("market",{})
    up_ct = sum(1 for md in mkt.values() if md.get("up"))
    mkt_str = " | ".join(f"{n}: {'▲' if md.get('up') else '▼'}{abs(md.get('change_pct',0))}%"
                          for n,md in mkt.items() if md.get("price"))
    base = int((up_ct/max(len(mkt),1))*100)
    if not GEMINI_API_KEY:
        result = {"score":base,"label":score_to_label(base),"categories":{},"entities":[]}
        await cache_set("sentiment_v3", result, 30); return result
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
Score 0=extreme fear, 50=neutral, 100=extreme greed. Entities: top 8 most mentioned.
MARKETS: {mkt_str}
HEADLINES:\n{headlines}"""
    try:
        text   = _model().generate_content(prompt).text.strip()
        text   = re.sub(r"^```[a-z]*\n?","",text).rstrip("```").strip()
        parsed = json.loads(text)
        cats   = parsed.get("categories",{})
        scores = [v.get("score",50) for v in cats.values() if isinstance(v,dict)]
        score  = int(sum(scores)/len(scores)) if scores else base
        result = {"score":score,"label":score_to_label(score),
                  "categories":cats,"entities":parsed.get("entities",[])}
    except Exception:
        result = {"score":base,"label":score_to_label(base),"categories":{},"entities":[]}
    await cache_set("sentiment_v3", result, 30)
    return result

@app.get("/api/trends")
async def get_trends():
    """Topic frequency analysis across today's headlines."""
    cached = await cache_get("trends_v3")
    if cached: return cached
    articles = await _fetch_articles()
    if not GEMINI_API_KEY or not articles:
        return {"topics":[],"timestamp":datetime.utcnow().isoformat()}
    headlines = "\n".join(f"- {a['title']}" for a in articles[:30])
    prompt = f"""Analyse these news headlines and identify recurring topics/themes.
Return ONLY valid JSON:
{{
  "topics": [
    {{"topic":"...","count":<how many headlines mention this>,"pct":<% of total headlines>,"category":"finance|tech|geopolitics|singapore|commodities|other","sentiment":"positive|negative|neutral"}}
  ]
}}
List top 8 topics. A topic should appear in at least 2 headlines. Total headlines: {len(articles)}.
HEADLINES:\n{headlines}"""
    try:
        text   = _model().generate_content(prompt).text.strip()
        text   = re.sub(r"^```[a-z]*\n?","",text).rstrip("```").strip()
        parsed = json.loads(text)
        result = {"topics":parsed.get("topics",[]),"timestamp":datetime.utcnow().isoformat()}
    except Exception:
        result = {"topics":[],"timestamp":datetime.utcnow().isoformat()}
    await cache_set("trends_v3", result, 30)
    return result

@app.get("/api/history")
async def get_history(symbol: str = "^GSPC", days: int = 30):
    days = max(7,min(days,365))
    cache_key = f"hist3_{symbol}_{days}"
    cached    = await cache_get(cache_key)
    if cached: return cached
    period_map = {7:"10d",30:"1mo",90:"3mo",180:"6mo",365:"1y"}
    period = next((v for k,v in period_map.items() if days<=k),"1y")
    try:
        hist = await asyncio.wait_for(
            asyncio.to_thread(yf.Ticker(symbol).history, period=period, interval="1d"),
            timeout=15.0
        )
        if hist.empty:
            return {"symbol":symbol,"prices":[],"sentiment":[],"stats":{},"error":"No data returned"}
        prices = [{"date":idx.strftime("%Y-%m-%d"),"price":round(float(row["Close"]),2)}
                  for idx,row in hist.iterrows()]
    except Exception as e:
        return {"symbol":symbol,"prices":[],"sentiment":[],"stats":{},"error":str(e)}
    if len(prices)<2:
        return {"symbol":symbol,"prices":prices,"sentiment":[],"stats":{}}
    vals  = [p["price"] for p in prices]
    stats = {"start":vals[0],"current":vals[-1],
              "change_pct":round((vals[-1]-vals[0])/vals[0]*100,2),
              "high":round(max(vals),2),"low":round(min(vals),2)}
    sentiment_data = []
    if supabase:
        try:
            from_date = (datetime.utcnow()-timedelta(days=days)).date().isoformat()
            rows = (supabase.table("sentiment_history").select("snapshot_date,score,label")
                    .gte("snapshot_date",from_date).order("snapshot_date").execute()).data or []
            sentiment_data = [{"date":r["snapshot_date"],"score":r["score"],"label":r.get("label","")} for r in rows]
        except Exception: pass
    result = {"symbol":symbol,"name":_NAME_MAP.get(symbol,symbol),
              "prices":prices,"sentiment":sentiment_data,"stats":stats}
    await cache_set(cache_key, result, 10)
    return result

@app.get("/api/stock-insights")
async def get_stock_insights(tickers: str = "AAPL,NVDA,TSLA"):
    """Per-stock AI insight using today's news context."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:8]
    cache_key   = "ins_"+"_".join(sorted(ticker_list))[:80]
    cached      = await cache_get(cache_key)
    if cached: return cached
    if not GEMINI_API_KEY:
        return {"insights":{t:"No AI key configured." for t in ticker_list}}
    brief_cache = await cache_get("brief_v3")
    hl = ""
    if brief_cache:
        hl = "\n".join(a.get("title","") for a in brief_cache.get("articles",[])[:20])
    prompt = f"""For each of these stocks, write ONE sentence explaining what's relevant in today's news context (or say "No specific news today" if nothing relevant). Be specific with company names and events.
Return ONLY valid JSON: {{"insights":{{{", ".join(f'"{t}":"..."' for t in ticker_list)}}}}}
TODAY'S HEADLINES:\n{hl}"""
    try:
        text   = _model().generate_content(prompt).text.strip()
        text   = re.sub(r"^```[a-z]*\n?","",text).rstrip("```").strip()
        parsed = json.loads(text)
        result = {"insights":parsed.get("insights",{})}
    except Exception:
        result = {"insights":{t:"Unable to load insight." for t in ticker_list}}
    await cache_set(cache_key, result, 30)
    return result

@app.get("/api/presets")
async def get_presets():
    return {"presets":{g:[{"symbol":s,"name":n} for s,n in items]
                        for g,items in WATCHLIST_PRESETS.items()},
            "defaults":DEFAULT_WATCHLIST}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not GEMINI_API_KEY:
        return {"response":"GEMINI_API_KEY not configured.","sources":[]}
    today_context, sources = "", []
    brief_cache = await cache_get("brief_v3")
    if brief_cache:
        ns  = brief_cache.get("news_summary",{})
        art = brief_cache.get("articles",[])
        mkt_str = " | ".join(f"{n}:{md['price']}({'▲' if md.get('up') else '▼'}{abs(md.get('change_pct',0))}%)"
                              for n,md in (brief_cache.get("market") or {}).items() if md.get("price"))
        bullets_obj = ns.get("bullets",{})
        bullets_flat = [b for cat in bullets_obj.values() for b in (cat if isinstance(cat,list) else [])]
        bullets_str  = "\n".join(f"- {b}" for b in bullets_flat)
        hl = "\n".join(f"- [{a.get('category','?').upper()}] {a.get('title','')}" for a in art[:14])
        today_context = (f"=== TODAY ===\nMarkets: {mkt_str}\n"
                         f"Sentiment: {ns.get('sentiment','?')} | Theme: {ns.get('top_theme','?')}\n"
                         f"Key points:\n{bullets_str}\nHeadlines:\n{hl}")
        sources.append("Today's data")
    history_context = await get_rag_context()
    if history_context: sources.append("Historical records")
    gem_history = []
    if today_context or history_context:
        ctx = "\n\n".join(filter(None,[today_context,history_context]))
        gem_history = [
            {"role":"user","parts":[f"Here is my context:\n\n{ctx}"]},
            {"role":"model","parts":["Understood. I have today's market data, news, and historical context. Ask away."]}
        ]
    for msg in req.history[-8:]:
        gem_history.append({"role":"user" if msg.role=="user" else "model","parts":[msg.content]})
    try:
        m = genai.GenerativeModel("gemini-2.0-flash",
            system_instruction=("Sharp, concise financial assistant for a Singapore user. "
                                 "Be specific with numbers. 2-4 sentences unless a list is better. "
                                 "If not in context, say so honestly."))
        answer = m.start_chat(history=gem_history).send_message(req.message).text.strip()
    except Exception:
        try:
            m = genai.GenerativeModel("gemini-1.5-flash-latest",
                system_instruction=("Sharp, concise financial assistant for a Singapore user. "
                                     "Be specific with numbers. 2-4 sentences unless a list is better."))
            answer = m.start_chat(history=gem_history).send_message(req.message).text.strip()
        except Exception as e:
            answer = f"Sorry, I ran into an issue: {str(e)[:140]}"
    return {"response":answer,"sources":sources}

handler = Mangum(app, lifespan="off")
