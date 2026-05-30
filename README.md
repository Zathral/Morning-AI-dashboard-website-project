# Morning Brief 🌅

A personalised AI morning dashboard built with FastAPI, Gemini, and plain HTML/CSS/JS. Deployed on Vercel.

Built for an AI & Data Engineering ePortfolio — Singapore Polytechnic.

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

## Supabase Setup

1. Go to [supabase.com](https://supabase.com) → New Project
2. Open the **SQL Editor** and run:

```sql
CREATE TABLE cache (
  key        TEXT PRIMARY KEY,
  data       JSONB        NOT NULL,
  expires_at TIMESTAMPTZ  NOT NULL,
  created_at TIMESTAMPTZ  DEFAULT NOW()
);
```

3. Copy your **Project URL** and **anon public key** from Settings → API into `.env`

---

## API Keys

### Gemini (Free)
1. Go to [aistudio.google.com](https://aistudio.google.com/app/apikey)
2. Click **Create API Key**
3. Paste into `GEMINI_API_KEY`

Free tier: 15 requests/min, 1M tokens/day — more than enough.

### Weather
No key needed — uses [Open-Meteo](https://open-meteo.com/) (completely free).

### Market Data
No key needed — uses `yfinance` (Yahoo Finance scraper).

---

## Deploy to Vercel

### Option A — Vercel CLI (recommended)

```bash
npm i -g vercel
vercel login
vercel
```

During setup:
- Framework: **Other**
- Root directory: `.` (current folder)
- Build command: leave blank
- Output directory: leave blank

### Option B — GitHub + Vercel Dashboard

1. Push your project to GitHub
2. Go to [vercel.com](https://vercel.com) → New Project → Import your repo
3. Framework: **Other**, everything else default

### Adding Environment Variables on Vercel

Vercel Dashboard → Your Project → **Settings → Environment Variables**

Add:
- `GEMINI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`

---

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
