"""MarketScout Streamlit frontend — brutalist intelligence terminal.

Backend integration is unchanged; this module only controls presentation.

Run with:
    streamlit run src/marketscout/frontend/app.py

Backend URL: MARKETSCOUT_API_URL env var (default http://localhost:8000).
"""

from __future__ import annotations

import os
from html import escape as _h

import requests
import streamlit as st

# ── Configuration ─────────────────────────────────────────────────────────────

_API_BASE = os.environ.get("MARKETSCOUT_API_URL", "http://localhost:8000").rstrip("/")
_TIMEOUT = 60  # seconds

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="MarketScout",
    layout="wide",
)

# ── Global CSS ────────────────────────────────────────────────────────────────

_GLOBAL_CSS = """
<style>
/* ── Reset & base ─────────────────────────────────────────────────── */
html, body, [class*="st-"] {
    font-family: "SFMono-Regular", "SF Mono", ui-monospace, Menlo,
                 "Courier New", monospace;
    color: #0A0A0A;
    font-size: 13px;
}
.stApp { background-color: #FFFFFF; }
.block-container {
    padding-top: 3rem;
    padding-bottom: 4rem;
    max-width: 1100px;
}

/* ── Header ───────────────────────────────────────────────────────── */
.ms-wordmark {
    font-size: 48px;
    font-weight: 900;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #000000;
    line-height: 1;
    margin: 0;
}
.ms-subtitle {
    font-size: 11px;
    font-weight: 400;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: #888888;
    margin: 0.6rem 0 0 0;
}

/* ── Section eyebrow with extending line ─────────────────────────── */
.ms-eyebrow-row {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 2.5rem;
    margin-top: 64px;
}
.ms-eyebrow-text {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.25em;
    text-transform: uppercase;
    color: #AAAAAA;
    white-space: nowrap;
    flex-shrink: 0;
}
.ms-eyebrow-line {
    flex: 1;
    height: 1px;
    background-color: #000000;
}

/* ── Stat block ───────────────────────────────────────────────────── */
.ms-stat { padding: 0; }
.ms-stat-number {
    font-size: 52px;
    font-weight: 800;
    color: #000000;
    line-height: 1;
    letter-spacing: -0.02em;
    font-family: "SFMono-Regular", ui-monospace, Menlo, monospace;
}
.ms-stat-text {
    font-size: 15px;
    font-weight: 700;
    color: #000000;
    line-height: 1.3;
    margin-top: 0.4rem;
    letter-spacing: 0.02em;
}
.ms-stat-empty {
    font-size: 13px;
    font-weight: 400;
    color: #AAAAAA;
    line-height: 1.3;
    margin-top: 0.4rem;
}
.ms-stat-label {
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #888888;
    margin-top: 0.5rem;
}

/* ── Target companies table ───────────────────────────────────────── */
.ms-table {
    width: 100%;
    border-collapse: collapse;
    font-family: "SFMono-Regular", ui-monospace, Menlo, monospace;
}
.ms-table th {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #AAAAAA;
    padding: 0 2rem 0.75rem 0;
    text-align: left;
    border-bottom: 1px solid #000000;
}
.ms-table td {
    padding: 0.85rem 2rem 0.85rem 0;
    border-bottom: 1px solid #E8E8E8;
    font-size: 13px;
    color: #0A0A0A;
    vertical-align: middle;
}
.ms-table td.td-company {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #000000;
}
.ms-table td.td-muted { color: #888888; font-size: 12px; }
.ms-table td.td-score {
    font-weight: 700;
    font-size: 13px;
    color: #000000;
    font-variant-numeric: tabular-nums;
}

/* ── Company intelligence blocks ──────────────────────────────────── */
.ms-company-block {
    border-top: 1px solid #E8E8E8;
    padding: 2rem 0 1.75rem 0;
}
.ms-company-name {
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #000000;
    margin-bottom: 1.5rem;
}
.ms-intel-section { margin-bottom: 1.1rem; }
.ms-intel-label {
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #AAAAAA;
    margin-bottom: 0.45rem;
}
.ms-intel-list {
    margin: 0;
    padding-left: 1rem;
    list-style: none;
}
.ms-intel-list li {
    font-size: 13px;
    font-weight: 400;
    color: #333333;
    line-height: 1.55;
    margin-bottom: 0.15rem;
    padding-left: 1rem;
    position: relative;
}
.ms-intel-list li::before {
    content: "—";
    position: absolute;
    left: 0;
    color: #CCCCCC;
}
.ms-intel-empty { font-size: 12px; color: #AAAAAA; }
.ms-pitch-value {
    font-size: 13px;
    font-weight: 600;
    color: #000000;
    line-height: 1.5;
}

/* ── Market context list ──────────────────────────────────────────── */
.ms-context-subhead {
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #AAAAAA;
    margin: 0 0 1rem 0;
}
.ms-context-list {
    list-style: none;
    margin: 0;
    padding: 0;
}
.ms-context-list li {
    font-size: 13px;
    font-weight: 400;
    color: #333333;
    line-height: 1.65;
    padding: 0.3rem 0;
    border-bottom: 1px solid #F0F0F0;
}
.ms-context-list li:last-child { border-bottom: none; }

/* ── Footnote ─────────────────────────────────────────────────────── */
.ms-footnote {
    font-size: 11px;
    color: #AAAAAA;
    letter-spacing: 0.05em;
    margin-top: 0.75rem;
}

/* ── Chat ─────────────────────────────────────────────────────────── */
.ms-chat-entry {
    border-top: 1px solid #E8E8E8;
    padding: 1.25rem 0 1rem 0;
}
.ms-chat-q {
    font-size: 13px;
    font-weight: 600;
    color: #000000;
    margin-bottom: 0.6rem;
    letter-spacing: 0.02em;
}
.ms-chat-a {
    font-size: 13px;
    font-weight: 400;
    color: #333333;
    line-height: 1.65;
    padding-left: 1.5rem;
    border-left: 2px solid #E8E8E8;
}
.ms-chat-dash { color: #000000; font-weight: 700; margin-right: 0.4rem; }

/* ── Streamlit overrides ──────────────────────────────────────────── */

/* Text inputs */
.stTextInput > div > div > input {
    background-color: #FAFAFA !important;
    color: #0A0A0A !important;
    border: 1px solid #000000 !important;
    border-radius: 0 !important;
    padding: 12px !important;
    font-family: "SFMono-Regular", ui-monospace, Menlo, monospace !important;
    font-size: 13px !important;
    caret-color: #000000;
}
.stTextInput > div > div > input::placeholder { color: #AAAAAA !important; }
.stTextInput label {
    color: #AAAAAA !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    font-family: "SFMono-Regular", ui-monospace, Menlo, monospace !important;
}

/* Form submit buttons (Run Search, Submit) */
.stFormSubmitButton > button {
    background-color: #F4F4F5 !important;
    color: #09090B !important;
    border: 1px solid #D4D4D8 !important;
    border-radius: 0 !important;
    padding: 12px 24px !important;
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em;
    text-transform: none;
    width: 100%;
    transition: background-color 0.15s ease, border-color 0.15s ease;
}
.stFormSubmitButton > button:hover {
    background-color: #E4E4E7 !important;
    border-color: #C0C0C4 !important;
    color: #09090B !important;
}

/* st.button (Send Briefing) → outlined, same clean style */
.stButton > button {
    background-color: #FFFFFF !important;
    color: #09090B !important;
    border: 1px solid #D4D4D8 !important;
    border-radius: 0 !important;
    padding: 12px 24px !important;
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em;
    text-transform: none;
    transition: background-color 0.15s ease;
}
.stButton > button:hover {
    background-color: #F4F4F5 !important;
    border-color: #C0C0C4 !important;
    color: #09090B !important;
}

/* Spinner */
.stSpinner > div > span {
    color: #888888 !important;
    font-family: "SFMono-Regular", ui-monospace, Menlo, monospace !important;
    font-size: 11px !important;
}

/* Alerts */
.stAlert { border-radius: 0 !important; }

/* Remove Streamlit's default top chrome bg */
header[data-testid="stHeader"] { background: #FFFFFF; }
</style>
"""

st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────

if "current_run" not in st.session_state:
    st.session_state["current_run"] = None
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []  # list[{"question": str, "answer": str}]


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
    """Composite score: 0.4 * signal_frequency + 0.3 * source_diversity + 0.3 * job_role_density."""
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
    """First non-empty company_name sourced exclusively from job postings.

    Only leads with ``signal_type == "job"`` are considered. News-based leads
    (signal_type == "news") are intentionally excluded — headline text often
    resolves to non-company strings that pollute the Target Companies table.
    A company appears in the table only when it has a real hiring signal.
    """
    for lead in opp.get("leads") or []:
        if not isinstance(lead, dict):
            continue
        if (lead.get("signal_type") or "").strip().lower() != "job":
            continue
        name = (lead.get("company_name") or "").strip()
        if name:
            return name
    return None


def _names_match(a: str, b: str) -> bool:
    """Case-insensitive company name equality."""
    return a.strip().lower() == b.strip().lower()


def _opportunities_for_company(opps: list, company: str) -> list[dict]:
    """Opportunities whose leads include this company."""
    matched: list[dict] = []
    for opp in opps:
        for lead in opp.get("leads") or []:
            if isinstance(lead, dict) and _names_match(
                lead.get("company_name") or "", company
            ):
                matched.append(opp)
                break
    return matched


def _belongs_to_run(item: dict, current_run_id) -> bool:
    """
    True if the signal dict is unstamped or matches the current run_id.

    Defensive: the backend stamps every job and headline with ``run_id`` so this
    filter normally matches everything in ``current_run``, but the check makes
    cross-run contamination impossible even if the session state is corrupted.
    """
    if current_run_id is None:
        return True
    rid = item.get("run_id")
    if rid is None:
        return True
    return rid == current_run_id


def _collect_company_intelligence(
    company: str,
    opps: list,
    run_data: dict,
) -> tuple[list[str], str]:
    """Return (hiring_titles, pitch) for the given company.

    Only job signals belonging to the current run_id are considered.
    """
    cl = company.strip().lower()
    current_run_id = run_data.get("run_id")
    jobs = run_data.get("jobs") or []

    hiring: list[str] = []
    seen_jobs: set[str] = set()
    for j in jobs:
        if not isinstance(j, dict):
            continue
        if not _belongs_to_run(j, current_run_id):
            continue
        if (j.get("company") or "").strip().lower() != cl:
            continue
        title = (j.get("title") or "").strip()
        if title and title.lower() not in seen_jobs:
            seen_jobs.add(title.lower())
            hiring.append(title)

    matched_opps = _opportunities_for_company(opps, company)
    for opp in matched_opps:
        for ev in opp.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            if (ev.get("source") or "").strip().lower() != "job":
                continue
            title = (ev.get("title") or "").strip()
            if title and title.lower() not in seen_jobs:
                seen_jobs.add(title.lower())
                hiring.append(title)

    pitch = ""
    if matched_opps:
        pitch = (matched_opps[0].get("problem") or matched_opps[0].get("title") or "").strip()

    return hiring, pitch


def _build_rows(
    opps: list,
    city: str,
    industry: str,
    run_data: dict | None = None,
) -> tuple[list[dict], int]:
    """Opportunities with a real lead company → deduplicated table rows + excluded count.

    Deduplication rules (applied in order):
    1. Only leads with ``signal_type == "job"`` are considered (via _company_from_leads).
    2. If the company has no actual job titles in the run's jobs list, it is excluded —
       this catches cases where a lead is flagged as "job" type but no real posting exists.
    3. Each company name appears at most once; when the same company surfaces in multiple
       opportunities, keep the row with the highest composite score.
    """
    # Collect all candidate rows keyed by normalised company name.
    # Map: lower(company) → best row dict seen so far.
    best_by_company: dict[str, dict] = {}
    excluded = 0

    for opp in opps:
        company = _company_from_leads(opp)
        if not company:
            excluded += 1
            continue
        sb = opp.get("score_breakdown") or {}
        composite = _composite_score_from_sb(sb)
        key = company.strip().lower()
        candidate = {
            "company": company,
            "city": city,
            "industry": industry,
            "composite_pct": round(composite * 100, 1),
            "signal_count": len(opp.get("evidence") or []),
        }
        existing = best_by_company.get(key)
        if existing is None or candidate["composite_pct"] > existing["composite_pct"]:
            best_by_company[key] = candidate

    # Gate: only keep companies with at least one real job title in the run.
    # This prevents news-sourced company names from leaking into the table even
    # when their lead is incorrectly tagged signal_type="job".
    # Also stores hiring_count so the table can sort by most-active-hiring first.
    rows: list[dict] = []
    for key, row in best_by_company.items():
        hiring: list[str] = []
        if run_data is not None:
            hiring, _ = _collect_company_intelligence(row["company"], opps, run_data)
            if not hiring:
                excluded += 1
                continue
        row["hiring_count"] = len(hiring)
        rows.append(row)

    rows.sort(key=lambda r: r["hiring_count"], reverse=True)
    return rows, excluded


def _top_opportunity(opps: list) -> str:
    """Highest-scoring opportunity category name across all opps."""
    best_name = ""
    best_score = -1.0
    for opp in opps:
        score = _composite_score_from_sb(opp.get("score_breakdown") or {})
        if score > best_score:
            best_score = score
            best_name = (opp.get("problem") or opp.get("title") or "").strip()
    if best_score <= 0:
        return ""
    return best_name


# ── Render helpers ────────────────────────────────────────────────────────────

def _eyebrow(label: str) -> None:
    """Section heading: small ALL CAPS label with a 1px black line extending right."""
    st.markdown(
        f'<div class="ms-eyebrow-row">'
        f'<span class="ms-eyebrow-text">{_h(label)}</span>'
        f'<div class="ms-eyebrow-line"></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _stat_block(col, *, value: str, label: str, empty: bool = False, big: bool = True) -> None:
    """Borderless editorial stat block."""
    if empty:
        value_html = f'<div class="ms-stat-empty">{_h(value)}</div>'
    elif big:
        value_html = f'<div class="ms-stat-number">{_h(value)}</div>'
    else:
        value_html = f'<div class="ms-stat-text">{_h(value)}</div>'
    col.markdown(
        f'<div class="ms-stat">'
        f'{value_html}'
        f'<div class="ms-stat-label">{_h(label)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _target_table_html(rows: list[dict]) -> str:
    """Custom HTML table for Target Companies — Company, City, Industry only.

    Company names longer than 40 characters are truncated with ellipsis.
    Rows are pre-sorted by hiring_count (most active hiring = top).
    """
    header = (
        '<table class="ms-table"><thead><tr>'
        '<th>Company</th><th>City</th><th>Industry</th>'
        '</tr></thead><tbody>'
    )

    def _trunc(name: str, limit: int = 40) -> str:
        return name if len(name) <= limit else name[:limit].rstrip() + "..."

    body = "".join(
        f"<tr>"
        f'<td class="td-company">{_h(_trunc(r["company"]))}</td>'
        f'<td class="td-muted">{_h(r["city"])}</td>'
        f'<td class="td-muted">{_h(r["industry"])}</td>'
        f"</tr>"
        for r in rows
    )
    return header + body + "</tbody></table>"


def _company_block_html(
    company: str,
    hiring: list[str],
    pitch: str,
) -> str:
    """HTML for one company intelligence block."""
    def _items(items: list[str]) -> str:
        if not items:
            return '<span class="ms-intel-empty">—</span>'
        lis = "".join(f"<li>{_h(t)}</li>" for t in items)
        return f'<ul class="ms-intel-list">{lis}</ul>'

    pitch_html = (
        f'<div class="ms-pitch-value">{_h(pitch)}</div>'
        if pitch
        else '<span class="ms-intel-empty">No mapped opportunity.</span>'
    )

    return (
        '<div class="ms-company-block">'
        f'<div class="ms-company-name">{_h(company)}</div>'
        '<div class="ms-intel-section">'
        '<div class="ms-intel-label">Hiring For</div>'
        f'{_items(hiring)}'
        '</div>'
        '<div class="ms-intel-section">'
        '<div class="ms-intel-label">What To Pitch</div>'
        f'{pitch_html}'
        '</div>'
        '</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(
    '<p class="ms-wordmark">MarketScout</p>'
    '<p class="ms-subtitle">Market Intelligence</p>',
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────────────────────────────────────────

_eyebrow("Search")

with st.form("search_form"):
    col_city, col_ind, col_btn = st.columns([3, 3, 1.4])
    with col_city:
        city_input = st.text_input("City", value="Vancouver", placeholder="e.g. Vancouver")
    with col_ind:
        industry_input = st.text_input(
            "Industry", value="Construction", placeholder="e.g. Construction"
        )
    with col_btn:
        st.write("")  # vertical alignment spacer
        submitted = st.form_submit_button("Run Search", use_container_width=True)

if submitted:
    with st.spinner("Running pipeline."):
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
                st.session_state["chat_history"] = []
            else:
                st.error(f"Pipeline error {resp.status_code}: {_detail(resp)}")
        except requests.exceptions.ConnectionError:
            st.error(
                f"Could not connect to the backend at {_API_BASE}. "
                "Start it with: PYTHONPATH=src uvicorn marketscout.backend.main:app --reload"
            )
        except requests.exceptions.Timeout:
            st.error("Request timed out after 60 s. The pipeline may still be running.")
        except Exception as exc:
            st.error(f"Unexpected error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# RESULTS  (only when a run exists)
# ─────────────────────────────────────────────────────────────────────────────

current_run = st.session_state["current_run"]

if current_run:
    opps = current_run.get("opportunities") or []
    city_label = current_run.get("city", "")
    industry_label = current_run.get("industry", "")
    signal_count = current_run.get("signal_count", 0)

    rows, excluded_from_table = _build_rows(opps, city_label, industry_label, current_run)
    top_opp_name = _top_opportunity(opps)

    # ── OVERVIEW ──────────────────────────────────────────────────────────────
    _eyebrow("Overview")

    col1, col2, col3 = st.columns(3, gap="large")
    _stat_block(col1, value=f"{signal_count:,}", label="Signals Captured")
    _stat_block(col2, value=f"{len(rows):,}", label="Companies Identified")
    if top_opp_name:
        _stat_block(col3, value=top_opp_name, label="Top Opportunity", big=False)
    else:
        _stat_block(col3, value="No signal detected", label="Top Opportunity", empty=True)

    # ── MARKET CONTEXT ────────────────────────────────────────────────────────
    current_run_id = current_run.get("run_id")
    raw_headlines = [
        h for h in (current_run.get("headlines") or [])
        if isinstance(h, dict)
        and (h.get("title") or "").strip()
        and _belongs_to_run(h, current_run_id)
    ]
    if raw_headlines:
        _eyebrow("Market Context")
        subhead = f"{city_label} · {industry_label} · Latest signals".strip(" ·")
        items_html = "".join(
            f'<li>— {_h((h.get("title") or "").strip())}</li>'
            for h in raw_headlines[:5]
        )
        st.markdown(
            f'<p class="ms-context-subhead">{_h(subhead)}</p>'
            f'<ul class="ms-context-list">{items_html}</ul>',
            unsafe_allow_html=True,
        )

    # ── TARGET COMPANIES ──────────────────────────────────────────────────────
    _eyebrow("Targets")

    if rows:
        st.markdown(_target_table_html(rows), unsafe_allow_html=True)
    else:
        st.markdown(
            '<p class="ms-footnote">No companies with identified hiring signals in this run.</p>',
            unsafe_allow_html=True,
        )

    if excluded_from_table > 0:
        plural = "s" if excluded_from_table != 1 else ""
        st.markdown(
            f'<p class="ms-footnote">'
            f'{excluded_from_table} additional market signal{plural} detected '
            "without company matches."
            "</p>",
            unsafe_allow_html=True,
        )

    # ── COMPANY INTELLIGENCE ──────────────────────────────────────────────────
    if rows:
        _eyebrow("Intelligence")
        for r in rows:
            company = r["company"]
            hiring, pitch = _collect_company_intelligence(
                company, opps, current_run
            )
            st.markdown(
                _company_block_html(company, hiring, pitch),
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# ASK A QUESTION
# ─────────────────────────────────────────────────────────────────────────────

_eyebrow("Query")

if not current_run:
    st.markdown(
        '<p class="ms-footnote" style="color:#AAAAAA;">'
        "Run a search first to enable market queries."
        "</p>",
        unsafe_allow_html=True,
    )
else:
    for entry in st.session_state["chat_history"]:
        st.markdown(
            '<div class="ms-chat-entry">'
            f'<div class="ms-chat-q">{_h(entry["question"])}</div>'
            '<div class="ms-chat-a">'
            f'<span class="ms-chat-dash">—</span>{_h(entry["answer"])}'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    with st.form("ask_form", clear_on_submit=True):
        question_input = st.text_input(
            "Question",
            placeholder="e.g. What is the top company hiring for?",
            label_visibility="collapsed",
            key="ask_input",
        )
        ask_submitted = st.form_submit_button("Submit")

    if ask_submitted:
        if not question_input.strip():
            st.warning("Please enter a question.")
        else:
            with st.spinner("Querying market data."):
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
                        st.markdown(
                            '<p class="ms-footnote" style="color:#888888;">'
                            "Query failed — try rephrasing your question."
                            "</p>",
                            unsafe_allow_html=True,
                        )
                except requests.exceptions.ConnectionError:
                    st.error("Could not connect to the backend.")
                except requests.exceptions.Timeout:
                    st.error("Request timed out.")
                except Exception:
                    st.markdown(
                        '<p class="ms-footnote" style="color:#888888;">'
                        "Query failed — try rephrasing your question."
                        "</p>",
                        unsafe_allow_html=True,
                    )
