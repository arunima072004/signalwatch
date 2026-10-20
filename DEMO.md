# SignalWatch Demo Script

This script shows the complete SignalWatch prototype in ~10 minutes.

## Prerequisites

`
pip install -r requirements.txt
python-dotenv, tavily-python, streamlit already installed.
.env contains CHANNEL3_API_KEY and TAVILY_API_KEY.
`

---

## Step 1 — Show live data accumulation

Run db_stats.py to confirm live Channel3 data is growing:

`powershell
python scripts/db_stats.py
`

You should see 54+ observations from 3 live Channel3 cycles, across 10 watchlist
products and 13 retailers. Run a new live cycle to add more:

`powershell
python scripts/run_cycle.py --source channel3 --provider cached
python scripts/db_stats.py
`

The observation count grows by ~18 each cycle.

---

## Step 2 — Run the replay demo

The replay re-runs the full 2015-2018 historical dataset through the identical
pipeline, detecting all 24 change events and investigating them with cached
Tavily results (no API credit cost for already-cached queries):

`powershell
python scripts/db_stats.py --db data/replay_demo.db
`

You should see:
- 967 observations (full Phase 1 dataset)
- 24 change events, all INVESTIGATED
- 24 assessments stored

---

## Step 3 — Open the dashboard

`powershell
streamlit run dashboard/app.py
`

In your browser at http://localhost:8501:

1. **Overview page** — shows watchlist (10 live products), cycle count,
   observation totals, and event status (24 INVESTIGATED in replay DB).
   Switch between "Live" and "Replay demo" in the sidebar to see both databases.

2. **Data Accumulation page** — bar chart of observations per cycle (Live DB).
   Each Channel3 cycle adds ~18 new rows. This is the proof of accumulation.

3. **Prices page** — pick a product (e.g. Sony WF-1000XM6 earbuds,
   4 retailer offers). See price by merchant. Live DB shows current market prices.

4. **Events page** — 24 events table in the replay DB. All INVESTIGATED.

5. **Event Detail page** — select evt_835c783f6785e8bf
   (Apple MacBook, Bestbuy.com, -26.7%):
   - PROMOTION: CONTRADICTS
   - PRODUCT_EVENT: CONTRADICTS
   - Uncertainty factors displayed
   - Pricing recommendation: HOLD (minimax regret decision)
   - Profit table, regret table, scenario probabilities
   - All assumptions listed explicitly

---

## Step 4 — Show a recommendation

`powershell
python scripts/recommend.py --event-id evt_835c783f6785e8bf --db data/replay_demo.db
`

Output shows:
- Recommended action: HOLD
- Profit table across (hold, match, undercut_2pct, undercut_5pct) × 3 competitor scenarios
- Regret table — HOLD has max_regret=0 (it is the current price, so no downside)
- LOW_DATA flag on scenario probabilities (only 1 event in this product's history)
- All assumptions printed explicitly

---

## Step 5 — Start the live loop (optional, leaves it running)

`powershell
.\scripts\start_live.ps1 -IntervalMinutes 360
`

Or to run in a background window:

`powershell
Start-Process powershell -ArgumentList "-NoExit -File .\scripts\start_live.ps1 -IntervalMinutes 360"
`

Check logs\live.log for progress.

---

## Important caveats (state these clearly in demo)

- **Zero live change events is expected** — the 10 watchlist products have only
  3 cycles of price history (< 1 hour). BOCPD needs many observations per
  product-merchant pair before a change point can be detected. Live events will
  appear once prices actually change and enough history has accumulated.
- **The replay demonstrates the full trigger path** using real historical data
  and real (cached) investigation results.
- **Elasticity, margin, and our_price in the recommendation are assumptions**,
  not estimates from data.
