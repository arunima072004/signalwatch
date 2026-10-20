# SignalWatch

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Competitive pricing intelligence: detect unusual price changes, investigate their causes, and generate pricing recommendations.

---

## Architecture

`
Channel3 API (live, current prices)
    |
    v  Channel3Adapter -> PriceObservation
    |
    v  SQLite (observations grow each cycle)
    |
    v  Incremental BOCPD (per product-merchant pair, state persisted)
    |
    |-- no change point -> wait for next cycle
    |
    v  ChangeEvent (same schema as Phase 1 batch)
    |
    v  HypothesisGenerator (8 hypothesis types)
    |
    v  InvestigationAgent (6 strategies, Tavily, cached)
    |
    v  VerificationAgent (8-dimensional evidence scoring)
    |
    v  EventAssessment (JSON + Markdown report)
    |
    v  DecisionRecommendation (minimax regret, scenario model)
    |
    v  Streamlit dashboard
`

**Replay mode:** same pipeline, driven by historical CSV data instead of Channel3.
This is the main demo path — all 24 historical events have been detected and investigated.

---

## Quick start

`ash
pip install -r requirements.txt
cp .env.example .env   # add CHANNEL3_API_KEY and TAVILY_API_KEY
`

### Dataset

The replay demo uses the [Datafiniti Electronics Products Pricing Data](https://www.kaggle.com/datasets/datafiniti/electronic-products-prices)
(14,592 product listings, 33,869 price observations after exploding `dateSeen` and cleaning;
licensed [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)).

The CSV is **not included** in this repository due to its size and license.

1. Download `DatafinitiElectronicsProductsPricingData.csv` from the Kaggle link above.
2. Place it **one level above** this repository:
   `../DatafinitiElectronicsProductsPricingData.csv`
3. Run preprocessing: `python scripts/preprocess.py`

The derived outputs (`data/events/`, `data/assessments/`, `data/replay_demo.db`) are
committed to this repository and shared under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
for non-commercial use, in accordance with the source data license.
Pre-processed outputs are included so the dashboard works without re-running preprocessing.

The data/search_cache/ directory contains Tavily search snippets (title, URL, publication date,
and a short excerpt) cached for offline reproducibility. Each snippet belongs to its original
publisher. No full page bodies are stored. These snippets are included solely to allow the replay
demo to run without issuing live API calls or reproducing full copyrighted text.


### Manage watchlist

`ash
python scripts/manage_watchlist.py list
python scripts/manage_watchlist.py add --query "Sony headphones"
python scripts/manage_watchlist.py add --product-id rmAiFzV
python scripts/manage_watchlist.py remove --product-id rmAiFzV
`

### Run one live cycle

`ash
python scripts/run_cycle.py --source channel3 --provider cached
`

### Run replay demo (historical data)

`ash
python scripts/run_cycle.py --source replay --provider cached --cycles 200 \
    --window-days 14 --db data/replay_demo.db
`

### Database statistics

`ash
python scripts/db_stats.py                        # live DB
python scripts/db_stats.py --db data/replay_demo.db  # replay DB
`

### Generate a pricing recommendation  *(model-assumption demo)*

> **The decision layer is a model-assumption demo, not a validated pricing policy.**
> Cost, demand sensitivity (beta), and base demand are configurable parameters,
> not estimates from historical sales data. The sensitivity table shows how
> the recommendation changes across different assumptions. For price-decrease
> events with LOW_DATA scenario probabilities, the model uniformly recommends
> RAISE_2PCT regardless of beta or cost_ratio — a structural consequence of
> assuming 100% no_response probability when there is only one historical event.
> Do not use this output as a production pricing decision.
### Generate a pricing recommendation

`ash
python scripts/recommend.py --event-id evt_835c783f6785e8bf \
    --db data/replay_demo.db --save
`

### Start the dashboard

`ash
streamlit run dashboard/app.py
`

Opens at http://localhost:8501. Switch between Live and Replay databases in the sidebar.

### Start the live loop

**Windows (foreground):**
`powershell
.\scripts\start_live.ps1 -IntervalMinutes 360
`

**Windows (background window):**
`powershell
Start-Process powershell -ArgumentList "-NoExit -File .\scripts\start_live.ps1"
`

**Linux/macOS:**
`ash
nohup ./scripts/start_live.sh 360 > logs/live.log 2>&1 &
`

Logs go to logs/live.log.

---

## .env variables

`
# Search provider
SEARCH_PROVIDER=cached
TAVILY_API_KEY=tvly-your-key-here
TAVILY_SEARCH_DEPTH=basic

# Channel3 live pricing
CHANNEL3_API_KEY=your-channel3-key-here

# Budget guards
MAX_INVESTIGATIONS_PER_CYCLE=3
MAX_SEARCH_QUERIES_PER_DAY=150
MAX_CHANNEL3_CALLS_PER_CYCLE=50
MAX_CHANNEL3_CALLS_PER_DAY=200
`

The budget guard checks **before starting** each investigation, not after it finishes.
An investigation that starts when `queries_today + cycle_queries = 149` (one below the cap)
will run to completion even if it issues 15–20 queries, finishing at ~164–169 total.
The cap is therefore a soft limit on when new investigations are *started*, not a hard
ceiling on total queries per day. To reduce over-run, lower `MAX_SEARCH_QUERIES_PER_DAY`
by one investigation's worth of queries (typically 15–25).

---

## What is not implemented

- Pricing recommendations, RL, forecasting, scenario simulation: Phase 4
- Dashboard alerting, authentication, multi-user access: Phase 5
- RAG, embeddings, vector databases, LLM integration
- PostgreSQL (SQLite is used; swap via repository interface)
- Real-time streaming (polling loop is the current mechanism)

---

## Limitations

**(a) Live change events need accumulated price history.**
The incremental BOCPD requires many observations per product-merchant pair before
detecting a regime change. A new watchlist produces no change events for days or
weeks, depending on price stability and polling frequency. Zero live events is
expected immediately after onboarding.

**(b) Replay demonstrates the trigger using historical data.**
The replay pipeline re-runs 2015-2018 Datafiniti pricing data through the identical
detection and investigation pipeline. It does not mix historical prices with live
Channel3 prices (there is an 8-year gap that would create false change points).

**(c) The decision layer uses assumptions, not estimates.**
elasticity, margin, and our_price in the ScenarioModel are configurable
parameters, not values estimated from sales data. The disclaimer
"Decision support under stated assumptions; elasticity and margin are not estimated
from data." appears in every recommendation output.

**(d) Investigation verdicts are heuristic and not accuracy-validated.**
Evidence extraction uses keyword matching and structural signals. Support levels
(SUPPORTS, CONSISTENT_WITH, etc.) are best-effort, not validated against ground truth.

**(e) Brand names that collide with common words pull irrelevant results.**
The domain exclusion list (yelp.com, indeed.com, etc.) reduces noise but cannot
eliminate it. The Sherwood A/V receiver is a documented example.

**(f) Channel3 returns current prices only.**
Price history exists only from when polling started. Investigations run on live
events will have thin evidence until enough history accumulates.

**(g) Channel3 offers contain no SKU or variant fields.**
A single Channel3 listing for "65 Inch 4K OLED Smart TV" may aggregate
prices from different screen-size variants or model years. The `offers`
array contains `url`, `domain`, `price`, `availability`, `condition`,
`max_commission_rate`, and `dimensions` only — no `sku`, `variant`, or
`model_number` fields. Cross-retailer price comparisons for large-SKU
categories (TVs, appliances) may conflate variant differences with genuine
price changes.

---

## Test suite

335 tests passing, 4 skipped when the Datafiniti CSV is absent:
- Phase 1 (BOCPD, preprocessing, features, events): 112
- Phase 2 (investigation, verification, search): 151
- Phase 3 (adapters, incremental BOCPD, storage, pipeline): 71
- Dashboard integration (AppTest, missing-DB): 1

The 4 skipped tests require data/processed/cleaned_data.csv (derived from the
Datafiniti CSV via python scripts/preprocess.py):
- 	ests/adapters/test_adapters.py::TestCsvAdapter::test_csv_adapter_produces_price_observations
- 	ests/adapters/test_adapters.py::TestCsvAdapter::test_csv_adapter_is_sale_not_false_when_missing
- 	ests/adapters/test_adapters.py::TestCsvAdapter::test_csv_adapter_watchlist_filter
- 	ests/bocpd/test_incremental.py::TestBatchEquivalence::test_equivalence_on_historical_series
---

## License

**Code** (src/, scripts/, 	ests/, dashboard/): [MIT License](LICENSE) — Copyright (c) 2026 Arunima.

**Data under data/**: derived from the
[Datafiniti Electronics Products Pricing Dataset](https://www.kaggle.com/datasets/datafiniti/electronic-products-prices)
and shared under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
for non-commercial use, in accordance with the source data license.
This includes data/events/, data/assessments/, data/replay_demo.db, and data/search_cache/.

**Search snippets** in data/search_cache/ belong to their original publishers
and are cached solely for offline reproducibility (see Dataset section above).
