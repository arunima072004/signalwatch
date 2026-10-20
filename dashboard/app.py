"""
dashboard/app.py
=================
SignalWatch Streamlit dashboard.

Usage:
  streamlit run dashboard/app.py
  streamlit run dashboard/app.py -- --db data/replay_demo.db

Pages:
  1. Overview        - watchlist, cycle counts, event status summary
  2. Data accumulation - observations per cycle chart
  3. Prices          - price history per product/merchant
  4. Events          - event table with status
  5. Event detail    - assessment + recommendation
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="SignalWatch",
    page_icon=":bar_chart:",
    layout="wide",
)

LIVE_DB    = str(ROOT / "data" / "signalwatch.db")
REPLAY_DB  = str(ROOT / "data" / "replay_demo.db")


@st.cache_resource
def get_connection(db_path: str):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_db_path():
    live_exists = Path(LIVE_DB).exists()
    options = ["Live (signalwatch.db)", "Replay demo (replay_demo.db)"]
    db_choice = st.sidebar.radio("Database", options, index=1)
    if "Live" in db_choice and not live_exists:
        st.info(
            "Live database (`data/signalwatch.db`) not found. "
            "Run `python scripts/run_cycle.py --source channel3 --provider cached` "
            "to create it. Showing replay database instead.",
            icon="ℹ️",
        )
        return REPLAY_DB
    return LIVE_DB if "Live" in db_choice else REPLAY_DB


def safe_query(conn, sql, params=()):
    try:
        return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

db_path = get_db_path()
conn = get_connection(db_path)

st.sidebar.markdown("---")
st.sidebar.caption(f"DB: {Path(db_path).name}")
if st.sidebar.button("Refresh"):
    st.cache_resource.clear()
    st.rerun()

page = st.sidebar.radio(
    "Page",
    ["Overview", "Data Accumulation", "Prices", "Events", "Event Detail"],
)

# ---------------------------------------------------------------------------
# 1. Overview
# ---------------------------------------------------------------------------

if page == "Overview":
    st.title("SignalWatch Overview")

    col1, col2, col3, col4, col5 = st.columns(5)

    wl_count = safe_query(conn, "SELECT COUNT(*) as n FROM watchlist WHERE active=1")
    total_obs = safe_query(conn, "SELECT COUNT(*) as n FROM observations")
    total_cycles = safe_query(conn, "SELECT COUNT(*) as n FROM pipeline_runs")
    total_events = safe_query(conn, "SELECT COUNT(*) as n FROM change_events")
    total_assess = safe_query(conn, "SELECT COUNT(*) as n FROM assessments")

    col1.metric("Watchlist products", int(wl_count["n"].iloc[0]) if not wl_count.empty else 0)
    col2.metric("Observations stored", int(total_obs["n"].iloc[0]) if not total_obs.empty else 0)
    col3.metric("Cycles run", int(total_cycles["n"].iloc[0]) if not total_cycles.empty else 0)
    col4.metric("Change events", int(total_events["n"].iloc[0]) if not total_events.empty else 0)
    col5.metric("Assessments", int(total_assess["n"].iloc[0]) if not total_assess.empty else 0)

    st.markdown("---")

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Watchlist")
        wl = safe_query(conn, "SELECT product_id, product_name, added_at FROM watchlist WHERE active=1 ORDER BY added_at")
        if not wl.empty:
            st.dataframe(
                wl,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "product_id": st.column_config.TextColumn("ID", width="small"),
                    "product_name": st.column_config.TextColumn("Product", width="large"),
                    "added_at": st.column_config.TextColumn("Added", width="medium"),
                },
            )
        else:
            st.info("Watchlist is empty.")

    with col_b:
        st.subheader("Change events by status")
        ev_status = safe_query(conn, "SELECT status, COUNT(*) as count FROM change_events GROUP BY status")
        if not ev_status.empty:
            st.dataframe(ev_status, use_container_width=True, hide_index=True)
        else:
            st.info("No change events yet.")

    st.subheader("Recent pipeline cycles")
    runs = safe_query(conn,
        "SELECT started_at, observations_ingested, events_created, events_investigated, "
        "channel3_calls_used, search_queries_used "
        "FROM pipeline_runs ORDER BY started_at DESC LIMIT 20")
    if not runs.empty:
        runs["started_at"] = runs["started_at"].str[:19]
        st.dataframe(runs, use_container_width=True, hide_index=True)
        if "replay" in db_path.lower():
            st.caption(
                "observations_ingested shows per-cycle fetch count (includes re-ingestion of "
                "already-stored rows). The 'Observations stored' metric above shows the actual "
                "deduplicated row count in the observations table."
            )

# ---------------------------------------------------------------------------
# 2. Data Accumulation
# ---------------------------------------------------------------------------

elif page == "Data Accumulation":
    st.title("Data Accumulation")
    st.caption("Visible proof that live pricing data is growing each cycle.")

    is_replay = "replay" in db_path.lower()
    runs = safe_query(conn,
        "SELECT started_at, observations_ingested FROM pipeline_runs ORDER BY started_at")
    if runs.empty:
        st.info("No pipeline runs recorded yet.")
    elif is_replay:
        real_obs = safe_query(conn, "SELECT COUNT(*) as n FROM observations")
        real_count = int(real_obs["n"].iloc[0]) if not real_obs.empty else 0
        total_ingested = int(runs["observations_ingested"].sum())

        st.info(
            "Replay database: accumulation charts show live Channel3 data only. "
            "The replay pipeline ran historical data through the same detection pipeline."
        )
        col1, col2, col3 = st.columns(3)
        col1.metric("Observations stored", real_count)
        col2.metric("Replay cycles", len(runs))
        col3.metric("Total ingested (inc. dedup)", total_ingested,
                    help="Sum of observations_ingested across all cycles. Higher than stored count because "
                         "duplicate observations (same product/merchant/timestamp) are deduplicated on insert.")

        st.subheader("Observations ingested per cycle (replay)")
        runs_plot = runs.copy()
        runs_plot["started_at"] = pd.to_datetime(runs_plot["started_at"], utc=True, errors="coerce")
        runs_plot = runs_plot.dropna(subset=["started_at"])
        if not runs_plot.empty:
            st.bar_chart(runs_plot.set_index("started_at")["observations_ingested"])

        st.caption(
            f"Note: {total_ingested} total ingested across {len(runs)} cycles vs "
            f"{real_count} stored rows — difference is deduplicated re-ingestion "
            f"of the same historical CSV data across multiple cycles."
        )
    else:
        runs["started_at"] = pd.to_datetime(runs["started_at"], utc=True, errors="coerce")
        runs = runs.dropna(subset=["started_at"])
        runs["cumulative"] = runs["observations_ingested"].cumsum()

        st.subheader("Observations added per cycle")
        st.bar_chart(runs.set_index("started_at")["observations_ingested"])

        st.subheader("Total observations over time")
        st.line_chart(runs.set_index("started_at")["cumulative"])

        total = int(runs["observations_ingested"].sum())
        n_cycles = len(runs)
        st.metric("Total observations", total)
        st.metric("Cycles with new data", int((runs["observations_ingested"] > 0).sum()))
        st.caption(f"Average {total/max(n_cycles,1):.1f} observations per cycle across {n_cycles} cycles.")

# ---------------------------------------------------------------------------
# 3. Prices
# ---------------------------------------------------------------------------

elif page == "Prices":
    st.title("Price History")

    wl = safe_query(conn, "SELECT product_id, product_name FROM watchlist WHERE active=1 ORDER BY product_name")
    if wl.empty:
        st.info("Watchlist is empty.")
    else:
        product_map = dict(zip(wl["product_name"].str[:60], wl["product_id"]))
        selected_name = st.selectbox("Product", list(product_map.keys()))
        selected_pid = product_map[selected_name]

        obs = safe_query(conn,
            "SELECT merchant, price, currency, observed_at FROM observations "
            "WHERE product_id = ? ORDER BY observed_at",
            (selected_pid,))

        if obs.empty:
            st.info(f"No observations yet for {selected_name}.")
        else:
            obs["observed_at"] = pd.to_datetime(obs["observed_at"], utc=True, errors="coerce")
            obs = obs.dropna(subset=["observed_at"])

            st.subheader("Price over time by merchant")
            if len(obs) > 1:
                pivot = obs.pivot_table(index="observed_at", columns="merchant", values="price", aggfunc="mean")
                # Use Altair for proper auto-scaling y-axis (no forced zero baseline)
                try:
                    import altair as alt
                    melted = pivot.reset_index().melt(id_vars="observed_at", var_name="merchant", value_name="price")
                    chart = alt.Chart(melted).mark_line(point=True).encode(
                        x=alt.X("observed_at:T", title="Date"),
                        y=alt.Y("price:Q", title="Price (USD)", scale=alt.Scale(zero=False)),
                        color="merchant:N",
                        tooltip=["observed_at:T","merchant:N","price:Q"],
                    ).interactive()
                    st.altair_chart(chart, use_container_width=True)
                except Exception:
                    st.line_chart(pivot)
            else:
                st.info("Need at least 2 observations for a time chart.")

            st.subheader("Latest prices by merchant")
            latest = obs.sort_values("observed_at").groupby("merchant").last().reset_index()
            latest = latest[["merchant","price","currency","observed_at"]].sort_values("price")
            latest["observed_at"] = latest["observed_at"].astype(str).str[:19]
            st.dataframe(latest, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# 4. Events
# ---------------------------------------------------------------------------

elif page == "Events":
    st.title("Change Events")

    events = safe_query(conn,
        "SELECT event_id, product_id, merchant, status, error, created_at, updated_at, event_json, "
        "evidence_source "
        "FROM change_events ORDER BY created_at DESC"
    )

    if events.empty:
        st.info("No change events yet. Run more pipeline cycles.")
    else:
        display = []
        for _, row in events.iterrows():
            try:
                ev = json.loads(row["event_json"])
                pct = ev.get("percentage_change") or 0
                direction = ev.get("change_direction","?")
                product = ev.get("product_name","?")[:45]
                ev_src = row["evidence_source"] if pd.notna(row.get("evidence_source")) else None
                display.append({
                    "event_id": row["event_id"],
                    "product": product,
                    "merchant": row["merchant"],
                    "change": f"{direction} {abs(pct):.1f}%",
                    "date": str(ev.get("observed_at",""))[:10],
                    "status": row["status"],
                    "evidence": ev_src or "?",
                })
            except Exception:
                pass

        df = pd.DataFrame(display)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.caption("Click Event Detail in the sidebar to inspect a specific event.")

# ---------------------------------------------------------------------------
# 5. Event Detail
# ---------------------------------------------------------------------------

elif page == "Event Detail":
    st.title("Event Detail")

    events = safe_query(conn, "SELECT event_id, product_id, merchant, status FROM change_events ORDER BY created_at DESC")
    if events.empty:
        st.info("No change events in this database.")
    else:
        event_ids = events["event_id"].tolist()
        selected_eid = st.selectbox("Select event", event_ids)

        # Load event
        ev_row = safe_query(conn,
            "SELECT event_json, status, evidence_source FROM change_events WHERE event_id = ?", (selected_eid,))
        if ev_row.empty:
            st.error("Event not found.")
        else:
            ev_json = json.loads(ev_row["event_json"].iloc[0])
            status = ev_row["status"].iloc[0]

            col1, col2 = st.columns(2)
            full_name = ev_json.get("product_name","?")
            col1.metric("Product", full_name[:40])
            if len(full_name) > 40:
                st.caption(full_name)
            col2.metric("Merchant", ev_json.get("merchant","?"))
            col1.metric("Price change",
                f"{ev_json.get('change_direction','?')} {abs(ev_json.get('percentage_change') or 0):.1f}%")
            col2.metric("Date", str(ev_json.get("observed_at",""))[:10])
            col_ev = ev_row["evidence_source"].iloc[0] if "evidence_source" in ev_row.columns else None
            if col_ev == "mock":
                st.warning("MOCK EVIDENCE: This assessment was produced with --provider mock. "
                           "Search results are canned test data, not real web evidence.")
            elif col_ev:
                st.success(f"Evidence source: {col_ev}")
            st.badge(status, color="green" if status=="INVESTIGATED" else "orange")

            st.markdown("---")

            # Assessment
            asmnt_row = safe_query(conn, "SELECT assessment_json FROM assessments WHERE event_id = ?", (selected_eid,))
            if not asmnt_row.empty:
                asmnt = json.loads(asmnt_row["assessment_json"].iloc[0])

                st.subheader("Hypothesis Assessments")
                ha_list = asmnt.get("hypothesis_assessments", [])
                for ha in ha_list:
                    sl = ha.get("support_level","?")
                    color = {"SUPPORTS":"green","PARTIALLY_SUPPORTS":"green","CONSISTENT_WITH":"blue",
                             "INSUFFICIENT_EVIDENCE":"grey","CONTRADICTS":"red"}.get(sl,"grey")
                    with st.expander(f"{ha.get('hypothesis_type','?')} — {sl}"):
                        st.write(ha.get("explanation",""))
                        cs = ha.get("component_scores",{})
                        if cs:
                            cs_df = pd.DataFrame([cs]).T.rename(columns={0:"score"})
                            st.bar_chart(cs_df)

                        sup_ids = ha.get("supporting_evidence_ids",[])
                        if sup_ids:
                            st.markdown("**Supporting evidence:**")
                            ev_pool = {e["evidence_id"]: e for e in asmnt.get("evidence",[])}
                            for eid in sup_ids[:3]:
                                ev = ev_pool.get(eid, {})
                                st.markdown(f"- [{ev.get('source_domain','?')}]({ev.get('source_url','#')}) "
                                           f"— {ev.get('claim','')[:100]}")

                st.markdown("---")
                uf = asmnt.get("uncertainty_factors",[])
                if uf:
                    st.subheader("Uncertainty Factors")
                    for u in uf:
                        st.warning(u)

            else:
                st.info("No assessment available. Investigation may be pending.")

            # Recommendation
            try:
                rec_row = conn.execute(
                    "SELECT rec_json FROM recommendations WHERE event_id = ?", (selected_eid,)
                ).fetchone()
                if rec_row:
                    rec = json.loads(rec_row[0])
                    st.markdown("---")
                    st.subheader("Pricing Recommendation")

                    chosen = rec.get("chosen_action","?")
                    st.warning(
                        "MODEL-ASSUMPTION DEMO — cost, demand sensitivity (beta), and "
                        "scenario probabilities are assumptions, not estimates from data. "
                        "Do not use as a production pricing decision."
                    )
                    st.success(f"Recommended action: **{chosen.upper()}**")

                    col_p, col_r = st.columns(2)
                    with col_p:
                        st.caption("Profit table (relative units)")
                        pt = rec.get("profit_table",{})
                        if pt:
                            pt_df = pd.DataFrame(pt).T
                            st.dataframe(pt_df.style.highlight_max(axis=0, color="lightgreen"), use_container_width=True)
                    with col_r:
                        st.caption("Regret table (minimise max)")
                        rt = rec.get("regret_table",{})
                        if rt:
                            rt_df = pd.DataFrame(rt).T
                            st.dataframe(rt_df.style.highlight_min(axis=0, color="lightgreen"), use_container_width=True)

                    sp = rec.get("scenario_probabilities",{})
                    conf = sp.get("confidence","?")
                    n = sp.get("sample_size",0)
                    st.caption(f"Scenario probabilities (competitor response model, n={n}, {conf})")
                    sp_display = {k: v for k,v in sp.items() if k in ["no_response","match","undercut"]}
                    if sp_display:
                        st.bar_chart(pd.DataFrame([sp_display]))

                    st.caption("Assumptions:")
                    for a in rec.get("assumptions",[]):
                        st.text(f"  - {a}")
                else:
                    st.info("No recommendation yet. Run: python scripts/recommend.py --event-id " + selected_eid + " --db " + Path(db_path).name + " --save")
            except Exception as exc:
                st.info("Recommendations table not yet created. Run recommend.py with --save.")
