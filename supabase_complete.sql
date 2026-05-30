-- ─────────────────────────────────────────────────────────────────────────────
-- Morning Brief · Complete Supabase Schema
-- Run this entire file in: Supabase Dashboard → SQL Editor → New Query → Run
--
-- What each table does:
--   cache            → stores API responses so repeat page loads are instant
--                      (brief 30min, weather 30min, market 5min, sentiment 30min)
--   watchlist        → saves your ticker list per browser session
--   market_history   → daily price snapshots used in the historical trend chart
--   sentiment_history→ daily AI sentiment scores; used in chart overlay + RAG chat
--
-- Safe to run multiple times — all statements use IF NOT EXISTS / OR REPLACE.
-- ─────────────────────────────────────────────────────────────────────────────


-- ── 1. Cache (most important — makes every page load faster) ─────────────────
CREATE TABLE IF NOT EXISTS cache (
  key        TEXT        PRIMARY KEY,
  data       JSONB       NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-delete expired rows so the table doesn't grow forever
-- (Supabase doesn't run cron jobs on free tier, but this index helps queries skip stale rows)
CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);


-- ── 2. Watchlist (saves your ticker list across browser sessions) ─────────────
CREATE TABLE IF NOT EXISTS watchlist (
  session_key TEXT        PRIMARY KEY,
  tickers     JSONB       NOT NULL DEFAULT '[]',
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);


-- ── 3. Market history (daily price snapshots for the historical trend chart) ──
CREATE TABLE IF NOT EXISTS market_history (
  snapshot_date DATE    NOT NULL,
  symbol        TEXT    NOT NULL,
  name          TEXT    NOT NULL,
  price         NUMERIC,
  change_pct    NUMERIC,
  PRIMARY KEY (snapshot_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_market_history_date   ON market_history(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_market_history_symbol ON market_history(symbol);


-- ── 4. Sentiment history (daily AI scores for chart overlay + RAG chatbot) ────
CREATE TABLE IF NOT EXISTS sentiment_history (
  snapshot_date DATE        PRIMARY KEY,
  score         INTEGER,           -- 0–100 fear/greed
  label         TEXT,              -- e.g. "Greed"
  sentiment     TEXT,              -- bullish/bearish/neutral/cautious
  top_theme     TEXT,
  key_entities  JSONB,
  bullets       JSONB,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sentiment_history_date ON sentiment_history(snapshot_date DESC);


-- ── Row Level Security ────────────────────────────────────────────────────────
-- Allows the anon key (used by the Python backend) to read and write all tables.
-- Without these policies, all queries will be silently blocked.

ALTER TABLE cache             ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist         ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_history    ENABLE ROW LEVEL SECURITY;
ALTER TABLE sentiment_history ENABLE ROW LEVEL SECURITY;

-- Drop existing policies first so this script is idempotent
DROP POLICY IF EXISTS "anon_all_cache"             ON cache;
DROP POLICY IF EXISTS "anon_all_watchlist"         ON watchlist;
DROP POLICY IF EXISTS "anon_all_market_history"    ON market_history;
DROP POLICY IF EXISTS "anon_all_sentiment_history" ON sentiment_history;

CREATE POLICY "anon_all_cache"             ON cache             FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "anon_all_watchlist"         ON watchlist         FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "anon_all_market_history"    ON market_history    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "anon_all_sentiment_history" ON sentiment_history FOR ALL USING (true) WITH CHECK (true);


-- ── Verify ────────────────────────────────────────────────────────────────────
-- After running, check all 4 tables exist:
SELECT table_name
FROM   information_schema.tables
WHERE  table_schema = 'public'
  AND  table_name IN ('cache','watchlist','market_history','sentiment_history')
ORDER  BY table_name;
-- Should return 4 rows. If fewer, re-run the script.
