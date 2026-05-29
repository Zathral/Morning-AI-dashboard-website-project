# Morning Brief

A personalised AI morning dashboard built with FastAPI, Gemini, and plain HTML/CSS/JS. Deployed on Vercel.

---

## Features (Version 1)

| Feature | Tech Used |
|---|---|
| AI Morning Brief | Gemini 1.5 Flash |
| News Aggregation & Sentiment | RSS Feeds + Gemini NLP |
| Live Market Data + Sparklines | yfinance (Yahoo Finance) |
| Singapore Weather Forecast | Open-Meteo API (free, no key) |
| API Response Caching | Supabase (PostgreSQL) |
| Serverless Deployment | Vercel + FastAPI + Mangum |

---

## Project Structure

```
morning-brief/
├── api/
│   └── index.py       ← FastAPI backend (all endpoints)
├── index.html         ← Frontend (served as static by Vercel)
├── style.css
├── app.js
├── requirements.txt
├── vercel.json
└── .env.example
```

---

## Local Development

### 1. Clone and install

```bash
git clone <your-repo>
cd morning-brief
pip install -r requirements.txt
```

### 2. Set up environment variables

```bash
cp .env.example .env
# Edit .env with your keys
```

### 3. Run locally

```bash
uvicorn api.index:app --reload --port 8000
```

Then open `index.html` directly in your browser, or serve it:

```bash
python -m http.server 3000
# Visit http://localhost:3000
```

> For local dev, update the fetch URLs in `app.js` from `/api/...` to `http://localhost:8000/api/...`

---

## API Keys


## Deploy to Vercel


## API Endpoints

| Endpoint | Description | Cache TTL |
|---|---|---|
| `GET /api/health` | Status check | — |
| `GET /api/brief?name=Jeremy` | AI brief + news bullets + sentiment | 30 min |
| `GET /api/weather` | Singapore forecast (Open-Meteo) | 30 min |
| `GET /api/market` | S&P, NASDAQ, STI, BTC, Gold, Oil | 5 min |

---

## Architecture

```
Browser
  ├── GET /api/brief    → FastAPI → Gemini 1.5 Flash
  │                              → RSS feeds (BBC, CNA, TechCrunch, CNBC)
  │                              → Open-Meteo (for brief context)
  │                              → yfinance (for brief context)
  │                              → Supabase cache (read/write)
  ├── GET /api/weather  → FastAPI → Open-Meteo → Supabase cache
  └── GET /api/market   → FastAPI → yfinance → Supabase cache
```

---

## Roadmap (V2+)

- [ ] AI Chat Assistant (RAG chatbot)
- [ ] Smart Watchlist (custom stocks/crypto)
- [ ] Sentiment heatmap & trend detection
- [ ] Historical news + sentiment tracking
- [ ] User auth via Supabase (personalised watchlists)
- [ ] Push notifications for major market events

---

## Tech Stack

- **Backend**: FastAPI (Python), Mangum (ASGI→Lambda adapter for Vercel)
- **AI**: Google Gemini 1.5 Flash
- **Market Data**: yfinance (Yahoo Finance)
- **Weather**: Open-Meteo (free, no API key)
- **News**: RSS feeds via feedparser
- **Database/Cache**: Supabase (PostgreSQL)
- **Frontend**: Vanilla HTML, CSS, JavaScript
- **Fonts**: Space Mono, Playfair Display, DM Sans
- **Hosting**: Vercel (Serverless Python)
