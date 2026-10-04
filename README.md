# SignalWatch

**Market intelligence pipeline for detecting and investigating unusual product pricing.**

SignalWatch monitors historical retail pricing data, detects statistically significant price changes using Bayesian Online Change-Point Detection (BOCPD), and then automatically investigates the most plausible explanations by running targeted web searches, extracting evidence, and producing a structured, evidence-backed assessment for each event.

---

## What it does

```
Raw pricing data (CSV)
         |
         v
Phase 1 — Statistical Detection
         |
         +---> Preprocessing & feature engineering
         +---> BOCPD change-point detection
         +---> Change event generation
         +---> Weak supervision labelling
         |
         v
Phase 2 — Investigation & Verification
         |
         +---> Hypothesis generation (8 hypothesis types)
         +---> Six investigation strategies (parallel)
         +---> Targeted web search via Tavily API
         +---> Evidence extraction with full provenance
         +---> Source independence analysis
         +---> Multi-dimensional verification
         +---> Structured EventAssessment (JSON + Markdown report)
```

**Phase 1** answers: *"Did something unusual happen to this price?"*

**Phase 2** answers: *"What plausible explanations can we find evidence for?"*

---

## Project structure

```
signalwatch/
├── src/
│   ├── bocpd/                  Bayesian Online Change-Point Detection
│   ├── data/                   Data loading, profiling, preprocessing
│   ├── timeseries/             Time-series construction per product-merchant pair
│   ├── features/               Price features + competitive features
│   ├── events/                 ChangeEvent generation from BOCPD results
│   ├── weak_supervision/       Heuristic labelling (promotion, competitive, etc.)
│   ├── query_generation/       Legacy deterministic query generator (Phase 1)
│   │
│   ├── investigation/          Phase 2 investigation pipeline
│   │   ├── hypothesis_generator.py   Generate hypotheses from ChangeEvent signals
│   │   ├── investigation_agent.py    InvestigationAgent + 6 strategies
│   │   ├── verification_agent.py     8-dimension evidence verification
│   │   └── orchestrator.py           End-to-end pipeline coordinator
│   │
│   ├── evidence/                Evidence extraction and HTML parsing
│   ├── search/                  SearchProvider abstraction
│   │   ├── provider_interface.py     Abstract base class
│   │   ├── mock_provider.py          Deterministic test double
│   │   ├── tavily_provider.py        Live Tavily API (with retry + domain exclusions)
│   │   └── cached_provider.py        Disk-backed cache wrapper
│   └── models/                  Data models (Hypothesis, Evidence, Assessment, etc.)
│
├── scripts/
│   ├── preprocess.py            Run Phase 1 preprocessing
│   ├── build_timeseries.py      Build time-series from preprocessed data
│   ├── run_bocpd.py             Run BOCPD detection
│   ├── generate_events.py       Generate ChangeEvent objects
│   ├── generate_queries.py      Generate deterministic queries (Phase 1 legacy)
│   ├── investigate_event.py     Investigate a single historical event (Phase 2)
│   └── generate_report.py       Generate Markdown report from assessment JSON
│
├── tests/
│   ├── test_bocpd.py ...        Phase 1 regression tests (112 tests)
│   ├── investigation/           Phase 2 unit tests
│   └── integration/             End-to-end pipeline tests (all 24 events, mock)
│
├── data/
│   ├── processed/               Preprocessed CSVs
│   ├── events/                  change_events.json (24 detected events)
│   ├── assessments/             EventAssessment JSONs + Markdown reports
│   ├── search_cache/            Cached Tavily search results (populated on first run)
│   └── figures/                 Visualisation charts from Phase 1 notebooks
│
├── notebooks/                   Exploratory Jupyter notebooks (Phase 1 analysis)
└── .env.example                 Environment variable template
```

---

## Current dataset

- **Source:** Datafiniti Electronics Product Pricing (historical CSV)
- **Observations:** 33,869 cleaned price observations
- **Product-merchant pairs:** 2,268 usable pairs
- **Detected change events:** 24 (from BOCPD with cp_probability >= 0.30)
- **Investigations completed:** 4 events investigated with real Tavily searches

---

## Hypothesis types

Each detected ChangeEvent is investigated against eight plausible explanations simultaneously. The system never forces a single winner — multiple hypotheses can be supported at once.

| Type | Question investigated |
|---|---|
| PROMOTION | Was this product specifically discounted or promoted? |
| COMPETITOR_RESPONSE | Did a competing retailer change price for the same product? |
| PRODUCT_EVENT | Was there a launch, discontinuation, recall, or successor announcement? |
| SEASONAL_EVENT | Was the retailer running a seasonal campaign (back-to-school, Black Friday)? |
| MARKET_EVENT | Were there broader industry, supply chain, or macroeconomic factors? |
| INVENTORY_LIQUIDATION | Is there external evidence of clearance or overstock? |
| MANUFACTURER_CHANGE | Did the manufacturer change MSRP or announce a product change? |
| DATA_ISSUE | Does the price change look like a data quality problem? |

---

## Verification

Each hypothesis is assessed across 8 dimensions:

| Dimension | What it measures |
|---|---|
| source_quality | Domain authority (known retailers, news, .gov/.edu) |
| temporal_alignment | Evidence publication date vs. event date |
| product_match | Does text name the specific product or brand? |
| merchant_match | Does text name the specific retailer? |
| specificity | Quantitative data, named entities, concrete claims |
| source_independence | INDEPENDENT / DUPLICATED / SYNDICATED / CONTRADICTING |
| causal_strength | Causal language present AND specific (keywords alone are not proof) |
| contradiction_penalty | Conflicting evidence detected |

Support levels (conservative vocabulary):

```
SUPPORTS                Strong, specific, direct, corroborated causal evidence
PARTIALLY_SUPPORTS      Some relevant evidence but incomplete
CONSISTENT_WITH         Temporal/topical alignment; no causation established
INSUFFICIENT_EVIDENCE   Too little or too vague to assess
CONTRADICTS             Evidence conflicts with the hypothesis
```

---

## Quick start

### Prerequisites

```bash
pip install -r requirements.txt
```

Requires Python 3.10+. For live web search, also install:

```bash
pip install tavily-python>=0.5.0 python-dotenv>=1.0.0
```

### Run Phase 1 (already done — outputs are in data/)

```bash
python scripts/preprocess.py
python scripts/build_timeseries.py
python scripts/run_bocpd.py
python scripts/generate_events.py
```

### Investigate a single event (mock provider — no API key needed)

```bash
python scripts/investigate_event.py --list
python scripts/investigate_event.py --event-id evt_835c783f6785e8bf --provider mock
```

### Investigate with live Tavily search

1. Copy `.env.example` to `.env` and add your Tavily API key:

```bash
cp .env.example .env
# edit .env: set TAVILY_API_KEY=tvly-your-key-here
```

Get a free key at https://app.tavily.com (1,000 credits/month, no credit card).

2. Run 2-3 events to populate the cache:

```bash
python scripts/investigate_event.py --event-id evt_835c783f6785e8bf --provider tavily
python scripts/investigate_event.py --event-id evt_c22613db89e21b31 --provider tavily
```

3. All subsequent runs use the cache (zero API credits):

```bash
python scripts/investigate_event.py --event-id evt_835c783f6785e8bf --provider cached
```

### Generate a Markdown report

```bash
# Single event
python scripts/generate_report.py data/assessments/evt_835c783f6785e8bf_assessment.json

# All saved assessments
python scripts/generate_report.py --all data/assessments/
```

---

## Example output

**Apple MacBook 12 (Core m5) — Bestbuy.com — August 2017 — price drop 26.7%**

```
PROMOTION              -> CONSISTENT_WITH
INVENTORY_LIQUIDATION  -> INSUFFICIENT_EVIDENCE
PRODUCT_EVENT          -> INSUFFICIENT_EVIDENCE
SEASONAL_EVENT         -> CONSISTENT_WITH
```

The evidence is consistent with a back-to-school promotional campaign at Best Buy in August 2017. Source independence could not be confirmed (multiple results from the same domain). No causal evidence was retrieved.

**Sherwood A/V Receiver — Walmart.com — December 2017 — price increase 44.9%**

```
PRODUCT_EVENT -> CONSISTENT_WITH
PROMOTION     -> CONTRADICTS
```

The PRODUCT_EVENT hypothesis is consistent with available evidence. The PROMOTION hypothesis is contradicted — "Sherwood" collides with the place name Sherwood, Oregon, pulling in local business listings. Domain exclusions (yelp.com, indeed.com, mapquest.com, rocketreach.co) are applied automatically to suppress this kind of noise.

---

## Configuration

All configuration via environment variables in `.env`:

| Variable | Default | Description |
|---|---|---|
| `SEARCH_PROVIDER` | `mock` | Which provider: `mock`, `tavily`, `cached` |
| `TAVILY_API_KEY` | — | Tavily API key (required for `tavily` and `cached`) |
| `TAVILY_SEARCH_DEPTH` | `basic` | `basic` (1 credit) or `advanced` (2 credits) |

### Domain exclusions

The Tavily provider excludes a default set of domains that produce irrelevant results for product-pricing queries:

```python
# Job boards, local directories, people-search sites
yelp.com, indeed.com, mapquest.com, rocketreach.co,
glassdoor.com, linkedin.com, zillow.com, yellowpages.com
```

Override for a specific run:

```python
from src.search.tavily_provider import TavilySearchProvider

# Add extra exclusions
provider = TavilySearchProvider(
    exclude_domains=["yelp.com", "indeed.com", "reddit.com"]
)

# Disable exclusions entirely
provider = TavilySearchProvider(exclude_domains=[])
```

---

## Search result caching

The `CachedSearchProvider` wraps any real provider with a disk cache at `data/search_cache/`. Cache key is the SHA-256 hash of the query text.

```
First run  (--provider tavily):   hits API, writes cache files
All later  (--provider cached):   reads from disk, zero API calls
```

Cache files are plain JSON and can be inspected or deleted individually.

---

## Tests

```bash
# All tests
pytest tests/ -q

# Phase 1 regression only
pytest tests/test_bocpd.py tests/test_events.py tests/test_preprocessing.py -q

# Phase 2 unit tests
pytest tests/investigation/ -q

# Integration (all 24 events, mock provider)
pytest tests/integration/ -q
```

**Current status: 263 tests passing** (112 Phase 1 + 151 Phase 2 + integration).

---

## What is NOT implemented

These are intentionally deferred:

- Real-time / streaming ingestion (Channel3)
- Dashboard or frontend UI
- RAG, embeddings, or vector databases
- LLM-based query refinement
- Reinforcement learning or pricing optimization
- PostgreSQL or other production databases
- Multi-user access / authentication

---

## Architecture notes

**Phase 2 uses one `InvestigationAgent` class with six strategy classes** (Promotion, Competitor, ProductEvent, News, RetailerEvent, Supply). All strategies run for every event — there is no early exit or confidence-based skipping. This is intentional: it prevents hypothesis anchoring and ensures minority explanations are always investigated.

**Evidence is two-dimensional:** `evidence_specificity` (DIRECT / INDIRECT) and `relationship_type` (CAUSAL / CORRELATIONAL / DESCRIPTIVE / UNKNOWN) are separate fields on every evidence item. Causal keywords in text are signals, not proof — the verification layer determines whether causality is genuinely established.

**Source independence is heuristic:** classifications (INDEPENDENT / DUPLICATED / SYNDICATED / CONTRADICTING) are best-effort approximations based on text similarity, attribution phrases, and cross-hypothesis URL sharing. They should be interpreted as signals, not ground truth.

---

## Citation

**Dataset:** Datafiniti (2019). *Electronics Products Prices*. Kaggle. https://www.kaggle.com/datasets/datafiniti/electronic-products-prices

**Algorithm:** Adams, R.P. & MacKay, D.J.C. (2007). *Bayesian Online Changepoint Detection*. https://arxiv.org/abs/0710.3742

**Live search:** Tavily Search API. https://tavily.com