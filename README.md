# Indian AI Stock

Stock intelligence platform for all NSE main-board stocks (about 2,550; NIFTY 100 is a filter): price models, a risk model, fundamentals, news sentiment, LLM explanations with RAG, and a paper portfolio, behind a FastAPI backend and a React UI.

> Research and education only, not investment advice. The walk-forward backtest found the models estimate price range and volatility well but do not predict direction, and no strategy beat buy-and-hold after costs. The UI shows those results next to the signals.

## Structure

```
backend/     FastAPI service: api/, services/, scripts/ (pipeline), db/
frontend/    React + Vite UI (5 screens)
data/        universe/ (NSE equity list, NIFTY 100 list, corporate actions), backtest/, chroma/ (vector store)
models/      Trained XGBoost models + metrics.json
notebooks/   Research & experiments
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # at the project root
pip install -r backend/requirements.txt
```

`backend/.env`:

```
DATABASE_URL=postgresql+psycopg2://postgres:<password>@localhost:5432/stock_ai
OPENAI_API_KEY=sk-...        # optional: enables sentiment, explanations, research answers
OPENAI_MODEL=gpt-5.4-mini    # optional
REDIS_URL=redis://localhost:6379   # optional: used if reachable, else in-memory cache
```

Load everything, then run the API and UI:

```bash
cd backend && python -m app.scripts.refresh --backtest   # first run ~45 min (fundamentals), then ~15 min daily
uvicorn app.main:app --reload                            # API on :8000, docs at /docs
cd ../frontend && npm install && npm run dev             # UI on http://localhost:5173
```

## Screens

| Screen | What it shows |
|---|---|
| Market Dashboard | Live indices, breadth across all covered stocks, sector returns, liquid movers, top WATCH signals, market news |
| AI Stock Screener | All 100 stock cards; filter by signal, risk, sector; sort by any score |
| Stock Deep Dive | The stock card (entry zone, targets, stop, 20D upside, risk, scores, Why?), price chart with the card's levels, fundamentals, news with sentiment, paper trade |
| News + AI Research | News feed per stock or market; questions answered from stock cards, model/backtest results and news, with numbered sources |
| Backtesting / Paper Portfolio | Paper positions that close at target or stop, the forward signal tracker, the walk-forward backtest |

## Load price history

Daily OHLCV for every NSE main-board stock in the EQ and BE series (max **6 months**, rolling) into the `stock_prices` table. Yahoo batch downloads, 100 symbols per request, about 3 minutes:

```bash
cd backend
python -m app.scripts.ingest                          # all NSE stocks (UNIVERSE in .env; default nse)
python -m app.scripts.ingest --keep-list              # skip re-downloading the stock lists
python -m app.scripts.ingest --universe nifty100      # NIFTY 100 only
python -m app.scripts.ingest RELIANCE TCS --period 1y   # specific stocks
```

The stock lists are snapshotted in `data/universe/`: `nse_equity.csv` (from NSE's `EQUITY_L.csv`; BZ-series and SME stocks are excluded) and `nifty100.csv`. Every universe run of `ingest` re-downloads both first, so new listings are picked up and delisted stocks stop being fetched; if NSE can't be reached it keeps the existing snapshot and says so (`--refresh-list` makes that a failure instead). Re-running is safe: rows are upserted, and anything older than 6 months is deleted.

## Build features

```bash
cd backend
python -m app.scripts.build_features
```

Rebuilds the `stock_features` table from `stock_prices`: one row per stock per day with 34 scale-free features (returns, trend, momentum, volatility, volume, price position, candle shape, and market context across all covered stocks). Every feature for day *t* uses only data up to day *t*'s close. Lookbacks are capped at 50 days to leave more usable rows from 6 months of prices. Series are split at corporate actions so no window crosses one: the dates in `data/universe/corporate_actions.csv`, plus any one-day move of −40% or worse, or +50% or more (NSE price bands make genuine moves that large very rare). Re-run after each ingest.

## Build the ML dataset

```bash
cd backend
python -m app.scripts.build_dataset
```

Joins `stock_features` with what happened next into the `ml_dataset` table. Targets are measured from day *t*'s close (a week = 5 trading days):

| Column | Meaning |
|---|---|
| `target_ret_1d` | Next day's close vs today's close |
| `target_ret_5d` | Close 5 trading days later vs today's close |
| `target_high_1d` | Next day's intraday high vs today's close |
| `target_high_5d` | Highest intraday high over the next 5 days vs today's close |
| `target_hit_5pct_5d` | 1 if that 5-day high is at least +5% |

`split` is chronological: `train` (first 70% of dates), `valid` (15%), `test` (last 15%). The 5 days before each boundary are marked `embargo` and excluded, so no training target overlaps a later period. The last 5 days have no targets yet and aren't in the dataset.

## Train and predict

```bash
cd backend
python -m app.scripts.train_model   # fit, report test-period results, save to models/xgb/
python -m app.scripts.predict       # latest-day predictions for all stocks -> stock_predictions
```

One XGBoost model per target. Trees are chosen on `valid`, results are scored once on `test`, and the saved models are refit on all labelled rows. Return models predict the expected % change in close. High models predict the **median** intraday high (about a 50% chance of reaching it), which `predict` converts to a rupee price. Test-period metrics are saved to `models/xgb/metrics.json`.

Full refresh, in order: `ingest` → `build_features` → `build_dataset` → `train_model` → `predict`.

## Backtest

```bash
cd backend
python -m app.scripts.backtest
```

Walk-forward: the models are retrained every 10 trading days on only the outcomes known at that point, then trade the next 10 days out of sample. Only stocks with a median of at least ₹5 crore traded a day are traded. Each signal day, buy the top 10 at the next open, then sell at a limit (+5% or the predicted 1-week high) or at the day-5 close. Capital is split into 5 sleeves so one is invested each day. Costs are 0.3% per round trip. The same rules are run on the 10 most volatile stocks, on all liquid stocks, and against buy-and-hold. With 6 months of prices the out-of-sample period is only about 2 months, too short to be statistically reliable; the forward signal tracker is the real test. Output goes to `data/backtest/`.

## Stock cards (signal engine)

```bash
cd backend
python -m app.scripts.ingest_fundamentals        # fundamentals snapshot for all stocks (~10 min; 4 parallel requests to stay under Yahoo's rate limit)
python -m app.scripts.build_signals --show TCS   # build today's cards; print one
python -m app.scripts.refresh                    # whole pipeline, ingest -> signals
```

One card per stock in `stock_signals`:

| Field | How it's made |
|---|---|
| Signal | WATCH / NEUTRAL / AVOID from a transparent rule on the scores; **not validated** as a predictor |
| Entry zone | Today's price down to 0.5 × ATR below it |
| Target 1 / 2 | Median forecast of the 1-week / 20-day high (about a 50% chance of reaching each) |
| Stop loss | 2 × ATR below today's price |
| 20D upside prob. | Model probability of touching +5% within 20 trading days |
| Risk | Low / Medium / High tercile of the risk model's predicted 20-day volatility |
| Technical, Momentum | Percentile vs all covered stocks today, from trend and return features |
| Liquidity | Median daily traded value over 20 days; WATCH needs at least ₹5 crore |
| Fundamental | Sector-relative percentiles of valuation, quality, growth and leverage (today's snapshot, so not backtestable) |
| News | Empty until the news service is built |

Stocks that traded today but have fewer than 51 trading days of usable prices (the features' 50-day lookback) still get a limited card, so new listings show up right away: signal **NEW** when NSE's listing date is about where their prices start, otherwise **LIMITED** (rarely traded, or history cut by a corporate action). These cards carry price, fundamentals, news and liquidity; entry zone, targets, stop, risk and technical/momentum scores stay empty until there is enough history. They are left out of the signal tracker.

API: `GET /api/signals` (filters: `signal`, `risk`, `sector`, `sort`, `limit`), `GET /api/signals/{symbol}`, `GET /api/model/performance`.

## News, sentiment and research (RAG)

```bash
cd backend
python -m app.scripts.ingest_news      # RSS -> news_articles, LLM sentiment, index into Chroma (~2 min)
python -m app.scripts.index_research   # stock cards + model/backtest docs into Chroma
```

- **News:** Google News search per stock, plus Economic Times, Livemint and Business Standard market feeds. Market articles are matched to stocks by company name, unique short name or ticker. At most 10 articles per stock from the **last 5 days**, fetched 8 in parallel. Articles older than 90 days are pruned.
- **Sentiment** (needs `OPENAI_API_KEY`): the LLM marks each article relevant or not and scores relevant ones from −1 to +1. The **news score** is 50 + 50 × the recency-weighted mean over 5 days, and is empty with fewer than 2 relevant articles. To keep OpenAI calls down, articles that never name the company are marked irrelevant locally without a call (about half of them), and the rest go 50 per call, mixed across stocks. Only unscored articles are sent, so later runs are small. It can't be backtested (no news history); the signal tracker measures it going forward.
- **RAG:** Chroma with local embeddings (no key needed to index or search). Questions retrieve the stock card, model/backtest/methodology docs and the most relevant news; the LLM answers only from those, citing `[n]`.
- **Why?:** LLM explanation of each card, cached per stock per day. Without a key the rule-based reasons are shown.

## Daily refresh

`python -m app.scripts.refresh` runs ingest → features → dataset → train → predict → fundamentals → news → signals → research index, and stops at the first failure. After each successful step it bumps a data version in the `app_meta` table; that version is part of every API cache key, so the API (Redis or in-memory cache) serves the new data within 10 seconds instead of waiting out cache TTLs. After running a single step by hand, `python -m app.scripts.clear_cache` does the same. To run it at 16:45 IST on weekdays, see [`backend/deploy/com.indianaistock.refresh.plist`](backend/deploy/com.indianaistock.refresh.plist) (macOS launchd; install steps are in the file).

## Paper portfolio

Positions open at the latest close with the card's Target 2 and stop loss. They close automatically on the first later day the low reaches the stop (checked first, to be conservative) or the high reaches the target, with gaps filled at the open. P&L includes 0.3% round-trip costs. The **signal tracker** reports the average 5- and 20-day return after each recorded day's WATCH / NEUTRAL / AVOID signals, compared with all stocks.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Status, cache backend, data version, LLM configured, data freshness |
| GET | `/api/market/indices` | NIFTY 50, SENSEX, NIFTY BANK, NIFTY IT (live, cached 60s) |
| GET | `/api/market/overview` | Breadth, movers, sectors, signal and risk mix |
| GET | `/api/stocks` | All covered stocks |
| GET | `/api/stocks/{symbol}/history?days=250` | Daily OHLCV + 20/50-day averages |
| GET | `/api/signals` | Stock cards (`signal`, `risk`, `sector`, `nifty100`, `sort`, `limit`; `compact=true` for the screener) |
| GET | `/api/signals/{symbol}` | One stock card |
| GET | `/api/signals/{symbol}/explanation` | LLM "Why?" (rule-based without a key) |
| GET | `/api/news?symbol=&days=&limit=` | News with sentiment (`symbol=MARKET` for market-wide) |
| POST | `/api/research/ask` | `{question, symbol?}` → answer with cited sources |
| GET | `/api/research/search?q=&symbol=` | Semantic search, no LLM needed |
| GET/POST | `/api/portfolio` | Paper positions / open one `{symbol, quantity, ...}` |
| POST | `/api/portfolio/{id}/close` | Close at the latest price |
| DELETE | `/api/portfolio/{id}` | Remove a position |
| GET | `/api/portfolio/signal-tracker` | Forward results of recorded signals |
| GET | `/api/backtest` | Walk-forward summary and equity curves |
| GET | `/api/model/performance` | Test-period model metrics |

> Market data comes from Yahoo Finance via `yfinance` and is for research/education only.

You need to run the sync at 16:45
