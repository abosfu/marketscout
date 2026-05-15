"""MarketScout — Streamlit frontend.

Three regions:
  1. Search Bar  (top)    — city + industry inputs, Run button
  2. Dashboard   (middle) — KPI strip, ranked targets table, signals chart
  3. Action Bar  (bottom) — NL2SQL chat (left) + email briefing (right)

Run with:
    streamlit run src/marketscout/frontend/app.py

Backend URL: MARKETSCOUT_API_URL env var (default http://localhost:8000).
"""

from __future__ import annotations

import json
import os

import pandas as pd
import requests
import streamlit as st

# ── Configuration ─────────────────────────────────────────────────────────────

_API_BASE = os.environ.get("MARKETSCOUT_API_URL", "http://localhost:8000").rstrip("/")
_TIMEOUT = 60  # seconds

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="MarketScout",
    page_icon="🎯",
    layout="wide",
)

# ── Session state ─────────────────────────────────────────────────────────────

if "current_run" not in st.session_state:
    st.session_state["current_run"] = None  # full /search response + city/industry
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []   # list of {"question": str, "answer": str}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _post(endpoint: str, payload: dict) -> requests.Response:
    """POST to the backend. Callers must handle ConnectionError / Timeout."""
    url = f"{_API_BASE}/{endpoint.lstrip('/')}"
    return requests.post(url, json=payload, timeout=_TIMEOUT)


def _detail(resp: requests.Response) -> str:
    """Extract the error detail string from a non-200 response."""
    try:
        return resp.json().get("detail", resp.text)
    except Exception:
        return resp.text


def _composite_score_from_sb(sb: dict | None) -> float:
    """Composite score from score_breakdown (signal_frequency/diversity/job_role_density)."""
    if not sb:
        return 0.0
    try:
        sf = float(sb.get("signal_frequency", 0.0))
        sd = float(sb.get("source_diversity", 0.0))
        jr = float(sb.get("job_role_density", 0.0))
    except Exception:
        return 0.0
    return float(sf * 0.4 + sd * 0.3 + jr * 0.3)


def _company_from_leads(opp: dict) -> str | None:
    """First non-empty company_name from leads; None if no identified company."""
    for lead in opp.get("leads") or []:
        if isinstance(lead, dict):
            name = (lead.get("company_name") or "").strip()
            if name:
                return name
    return None


def _build_rows(opps: list, city: str, industry: str) -> tuple[list[dict], int]:
    """Map opportunities with identified companies to table rows.

    Returns (rows, excluded_count) for opportunities skipped (no lead company).
    """
    rows: list[dict] = []
    excluded = 0
    rank = 0
    for opp in opps:
        company = _company_from_leads(opp)
        if not company:
            excluded += 1
            continue
        rank += 1
        sb = opp.get("score_breakdown") or {}
        total_score = round(_composite_score_from_sb(sb), 3)
        rows.append(
            {
                "company": company,
                "total_score": total_score,
                "rank": rank,
                "signal_count": len(opp.get("evidence") or []),
                "city": city,
                "industry": industry,
            }
        )
    return rows, excluded


# ─────────────────────────────────────────────────────────────────────────────
# REGION 1 — Search Bar
# ─────────────────────────────────────────────────────────────────────────────

st.title("🎯 MarketScout")

with st.form("search_form"):
    col_city, col_ind, col_btn = st.columns([3, 3, 1])
    with col_city:
        city_input = st.text_input("City", value="Vancouver", placeholder="e.g. Vancouver")
    with col_ind:
        industry_input = st.text_input(
            "Industry", value="Construction", placeholder="e.g. Construction"
        )
    with col_btn:
        st.write("")  # vertical alignment spacer
        submitted = st.form_submit_button("Run", use_container_width=True)

if submitted:
    with st.spinner("Running pipeline — fetching signals, scoring opportunities…"):
        try:
            resp = _post(
                "/search",
                {"city": city_input.strip(), "industry": industry_input.strip()},
            )
            if resp.status_code == 200:
                data = resp.json()
                data["city"] = city_input.strip()
                data["industry"] = industry_input.strip()
                st.session_state["current_run"] = data
                st.session_state["chat_history"] = []  # reset history for new run
            else:
                st.error(f"Pipeline error {resp.status_code}: {_detail(resp)}")
        except requests.exceptions.ConnectionError:
            st.error(
                f"Could not connect to the backend at **{_API_BASE}**. "
                "Start it with: `PYTHONPATH=src uvicorn marketscout.backend.main:app --reload`"
            )
        except requests.exceptions.Timeout:
            st.error(
                "Request timed out after 60 s. "
                "The pipeline may still be running — try again shortly."
            )
        except Exception as exc:
            st.error(f"Unexpected error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# REGION 2 — Dashboard  (only renders when a run exists)
# ─────────────────────────────────────────────────────────────────────────────

current_run = st.session_state["current_run"]

if current_run:
    opps = current_run.get("opportunities") or []
    city_label = current_run.get("city", "")
    industry_label = current_run.get("industry", "")
    signal_count = current_run.get("signal_count", 0)

    rows, excluded_from_table = _build_rows(opps, city_label, industry_label)
    rows_sorted = sorted(rows, key=lambda r: r["total_score"], reverse=True)
    top_score = round(rows_sorted[0]["total_score"], 2) if rows_sorted else 0.0

    st.divider()

    # ── A) KPI Strip ──────────────────────────────────────────────────────────
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("Signals Captured", signal_count)
    kpi2.metric("Opportunities Ranked", len(opps))
    with kpi3:
        st.markdown("**Top Score**")
        if top_score > 0:
            st.markdown(f"**{top_score:.2f}**")
        else:
            st.markdown(
                '<p style="color:#888; margin:0">No signal detected</p>',
                unsafe_allow_html=True,
            )

    st.write("")

    # ── B) Top Ranked Targets ─────────────────────────────────────────────────
    st.subheader("Top Ranked Targets")

    table_html = [
        "<table style='width:100%; border-collapse:collapse'>",
        "<thead><tr>"
        "<th style='text-align:left; padding:8px'>Company</th>"
        "<th style='text-align:left; padding:8px'>Composite score</th>"
        "<th style='text-align:right; padding:8px'>Rank</th>"
        "<th style='text-align:right; padding:8px'>Signal count</th>"
        "<th style='text-align:left; padding:8px'>City</th>"
        "<th style='text-align:left; padding:8px'>Industry</th>"
        "</tr></thead><tbody>",
    ]
    for r in rows_sorted:
        ts = float(r["total_score"])
        score_cell = (
            '<span style="color:#888">No signal detected</span>'
            if ts <= 0
            else f"{ts:.3f}"
        )
        co = str(r.get("company", "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        city_esc = str(r.get("city", "")).replace("&", "&amp;").replace("<", "&lt;")
        ind_esc = str(r.get("industry", "")).replace("&", "&amp;").replace("<", "&lt;")
        table_html.append(
            "<tr>"
            f"<td style='padding:8px'>{co}</td>"
            f"<td style='padding:8px'>{score_cell}</td>"
            f"<td style='padding:8px; text-align:right'>{r.get('rank', '')}</td>"
            f"<td style='padding:8px; text-align:right'>{r.get('signal_count', '')}</td>"
            f"<td style='padding:8px'>{city_esc}</td>"
            f"<td style='padding:8px'>{ind_esc}</td>"
            "</tr>"
        )
    table_html.append("</tbody></table>")
    st.markdown("".join(table_html), unsafe_allow_html=True)
    if excluded_from_table > 0:
        plural = "s" if excluded_from_table != 1 else ""
        st.markdown(
            "<p style='color:#888; margin-top:0.75rem'>"
            "Only showing targets with identified companies. "
            f"{excluded_from_table} additional market signal{plural} detected "
            "without company matches."
            "</p>",
            unsafe_allow_html=True,
        )

    # Expandable score_breakdown per opportunity (sorted by composite score)
    opps_sorted = sorted(
        opps,
        key=lambda o: _composite_score_from_sb(o.get("score_breakdown") or {}),
        reverse=True,
    )
    for opp in opps_sorted:
        sb = opp.get("score_breakdown")
        if sb:
            label = (opp.get("title") or "Opportunity")[:60]
            with st.expander(label):
                st.code(json.dumps(sb, indent=2), language="json")

    st.write("")

    # ── C) Market Signals ─────────────────────────────────────────────────────
    st.subheader("Market Signals")
    if opps:
        chart_rows: list[dict[str, float]] = []
        for opp in opps:
            sb = opp.get("score_breakdown") or {}
            sf = float(sb.get("signal_frequency", 0.0)) if sb else 0.0
            category = (opp.get("problem") or opp.get("title") or "Opportunity").strip()
            if sf > 0:
                chart_rows.append({"category": category, "signal_frequency": sf})
            else:
                st.markdown(f"**{category}**")
                st.markdown(
                    '<p style="color:#888; margin:0 0 0.75rem 0">No signal detected</p>',
                    unsafe_allow_html=True,
                )
        if chart_rows:
            chart_df = pd.DataFrame(chart_rows).set_index("category")[
                ["signal_frequency"]
            ]
            st.bar_chart(chart_df)


# ─────────────────────────────────────────────────────────────────────────────
# REGION 3 — Action Bar  (always visible)
# ─────────────────────────────────────────────────────────────────────────────

st.divider()
left_col, right_col = st.columns([7, 3])

# ── Left (70%): NL2SQL chat ───────────────────────────────────────────────────

with left_col:
    st.subheader("Ask a Question")

    # Render full chat history above the input
    for entry in st.session_state["chat_history"]:
        st.markdown(f"**You:** {entry['question']}")
        st.markdown(entry["answer"])
        st.write("")

    question_input = st.text_input(
        "Question",
        placeholder="e.g. Which opportunities have the highest pain score?",
        label_visibility="collapsed",
        key="ask_input",
    )
    ask_clicked = st.button("Ask")

    if ask_clicked:
        if not question_input.strip():
            st.warning("Please enter a question.")
        elif not current_run:
            st.warning("Run a search first to populate the database.")
        else:
            with st.spinner("Querying market data…"):
                try:
                    resp = _post(
                        "/ask",
                        {
                            "question": question_input.strip(),
                            "run_id": current_run["run_id"],
                        },
                    )
                    if resp.status_code == 200:
                        answer = resp.json().get("insights", "No insights returned.")
                        st.session_state["chat_history"].append(
                            {"question": question_input.strip(), "answer": answer}
                        )
                        st.rerun()
                    else:
                        st.error(f"Error {resp.status_code}: {_detail(resp)}")
                except requests.exceptions.ConnectionError:
                    st.error("Could not connect to the backend.")
                except requests.exceptions.Timeout:
                    st.error("Request timed out.")
                except Exception as exc:
                    st.error(f"Unexpected error: {exc}")

# ── Right (30%): Email briefing ───────────────────────────────────────────────

with right_col:
    st.subheader("Email Briefing")
    email_clicked = st.button("Send to Email", use_container_width=True)

    if email_clicked:
        if not current_run:
            st.warning("Run a search first.")
        else:
            with st.spinner("Sending briefing…"):
                try:
                    resp = _post(
                        "/email",
                        {
                            "run_id": current_run["run_id"],
                            "opportunities": current_run.get("opportunities", []),
                            "city": current_run.get("city", ""),
                            "industry": current_run.get("industry", ""),
                        },
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        if result.get("sent"):
                            st.success(result.get("detail", "Briefing sent."))
                        else:
                            st.error(result.get("detail", "Failed to send briefing."))
                    else:
                        st.error(f"Error {resp.status_code}: {_detail(resp)}")
                except requests.exceptions.ConnectionError:
                    st.error("Could not connect to the backend.")
                except requests.exceptions.Timeout:
                    st.error("Request timed out.")
                except Exception as exc:
                    st.error(f"Unexpected error: {exc}")
