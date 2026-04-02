"""MarketScout AI — Streamlit chat frontend.

Connects to the FastAPI NL2SQL backend at http://localhost:8000/api/ask.
Run with:
    streamlit run src/marketscout/frontend/app.py
"""

from __future__ import annotations

import requests
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="MarketScout AI",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Constants ─────────────────────────────────────────────────────────────────

API_URL = "http://localhost:8000/api/ask"
REQUEST_TIMEOUT = 60  # seconds — Gemini can take a moment on the first call

# ── Header ────────────────────────────────────────────────────────────────────

st.title("🧭 MarketScout AI")
st.subheader(
    "AI-powered market intelligence — ask a question, get a business insight.",
    divider="gray",
)
st.caption(
    "Backed by a live SQLite database of market signals. "
    "The engine generates SQL from your question, runs it, and synthesises the result "
    "into a plain-English insight."
)

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("About")
    st.markdown(
        """
**MarketScout AI** turns natural-language questions about your market signals
into structured SQL queries and readable business insights.

**Example questions**
- How many opportunities have a pain score over 7?
- Which industry has the highest average ROI signal?
- Show me the top 5 opportunities by confidence score.
- What is the average coverage score across all runs?
        """
    )
    st.divider()
    st.markdown("**Backend:** `http://localhost:8000`")
    st.markdown("**Docs:** [localhost:8000/docs](http://localhost:8000/docs)")

# ── Session state ─────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages: list[dict[str, str]] = []

# ── Render chat history ───────────────────────────────────────────────────────

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("sql_query"):
            with st.expander("View generated SQL"):
                st.code(message["sql_query"], language="sql")

# ── Chat input ────────────────────────────────────────────────────────────────

if prompt := st.chat_input("Ask a question about your market signals…"):

    # Append and display the user turn
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call the backend
    with st.chat_message("assistant"):
        with st.spinner("Analyzing market signals…"):
            try:
                response = requests.post(
                    API_URL,
                    json={"user_question": prompt},
                    timeout=REQUEST_TIMEOUT,
                )

                if response.status_code == 200:
                    data = response.json()
                    insights: str = data.get("insights", "No insights returned.")
                    sql_query: str = data.get("sql_query", "")

                    st.markdown(insights)
                    if sql_query:
                        with st.expander("View generated SQL"):
                            st.code(sql_query, language="sql")

                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": insights,
                            "sql_query": sql_query,
                        }
                    )

                elif response.status_code == 400:
                    detail = response.json().get("detail", "Bad request.")
                    st.error(f"**Request rejected:** {detail}")
                    st.session_state.messages.append(
                        {"role": "assistant", "content": f"⚠️ Request rejected: {detail}"}
                    )

                elif response.status_code == 503:
                    detail = response.json().get("detail", "Service unavailable.")
                    st.error(
                        f"**Backend not configured:** {detail}\n\n"
                        "Make sure `GOOGLE_API_KEY` is exported before starting the server."
                    )
                    st.session_state.messages.append(
                        {"role": "assistant", "content": f"⚠️ Backend not configured: {detail}"}
                    )

                else:
                    detail = response.json().get("detail", response.text)
                    st.error(f"**API error {response.status_code}:** {detail}")
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": f"⚠️ API error {response.status_code}: {detail}",
                        }
                    )

            except requests.exceptions.ConnectionError:
                msg = (
                    "**Could not connect to the MarketScout API.** "
                    "Is the backend running? Start it with:\n\n"
                    "```bash\n"
                    "PYTHONPATH=src uvicorn marketscout.backend.main:app --reload\n"
                    "```"
                )
                st.error(msg)
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"⚠️ {msg}"}
                )

            except requests.exceptions.Timeout:
                msg = (
                    "The request timed out after "
                    f"{REQUEST_TIMEOUT} seconds. "
                    "The Gemini model may be under load — please try again."
                )
                st.error(msg)
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"⚠️ {msg}"}
                )

            except Exception as exc:  # noqa: BLE001
                msg = f"Unexpected error: {exc}"
                st.error(msg)
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"⚠️ {msg}"}
                )
