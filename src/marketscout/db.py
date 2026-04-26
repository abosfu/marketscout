"""Gold layer: SQLAlchemy ORM models and transactional write path (Star Schema).

Tables:
  dim_runs          — one row per pipeline run
  dim_opportunities — one row per scored opportunity per run
  dim_signals       — one row per raw headline/job signal per run
  fact_leads        — one row per (opportunity, evidence) pair per run

All paths are resolved via fs.project_root(); nothing is hardcoded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from marketscout.fs import project_root  # noqa: F401 — establishes path resolution anchor

__all__ = ["init_db", "write_gold", "get_readonly_engine"]

logger = logging.getLogger(__name__)


# ── ORM models ────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class DimRun(Base):
    __tablename__ = "dim_runs"

    id = Column(String, primary_key=True)
    city = Column(String, nullable=False, default="")
    industry = Column(String, nullable=False, default="")
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    signal_count = Column(Integer, default=0)


class DimOpportunity(Base):
    __tablename__ = "dim_opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("dim_runs.id"), nullable=False)
    company = Column(String, default="")
    city = Column(String, default="")
    industry = Column(String, default="")
    total_score = Column(Float, default=0.0)
    rank = Column(Integer, default=0)
    signal_count = Column(Integer, default=0)


class DimSignal(Base):
    __tablename__ = "dim_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("dim_runs.id"), nullable=False)
    source = Column(String, default="")
    title = Column(String, default="")
    summary = Column(Text, default="")
    url = Column(String, default="")
    captured_at = Column(DateTime, nullable=True)
    content_hash = Column(String, default="")


class FactLead(Base):
    __tablename__ = "fact_leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("dim_runs.id"), nullable=False)
    opp_id = Column(Integer, ForeignKey("dim_opportunities.id"), nullable=False)
    signal_id = Column(Integer, ForeignKey("dim_signals.id"), nullable=True)
    pain_score = Column(Float, default=0.0)
    roi_score = Column(Float, default=0.0)
    confidence_score = Column(Float, default=0.0)
    score_breakdown = Column(Text, default="{}")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _content_hash(title: str, url: str) -> str:
    """SHA-256 based 32-char hash for deduplication."""
    return hashlib.sha256(f"{title}|{url}".encode()).hexdigest()[:32]


def _parse_dt(ts: str | None) -> datetime | None:
    """Parse an RSS or ISO-8601 timestamp into a datetime, or return None."""
    if not ts:
        return None
    from email.utils import parsedate_to_datetime
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        pass
    try:
        return parsedate_to_datetime(ts)
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def init_db(db_path: str | Path) -> None:
    """Create all Gold layer tables if they don't exist. Safe to call repeatedly."""
    db_path = Path(db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()


def write_gold(
    run_id: str,
    city: str,
    industry: str,
    opportunities: Sequence[Any],
    signals: Sequence[dict[str, Any]],
    *,
    db_path: str | Path | None = None,
) -> None:
    """
    Write one pipeline run to the Gold layer (Star Schema) in a single transaction.

    Idempotent: if run_id already exists the function returns immediately without
    writing any rows.  On any failure the entire transaction is rolled back.

    Args:
        run_id:        UUID string for this pipeline run.
        city:          Canonical city name.
        industry:      Canonical industry name.
        opportunities: Sequence of OpportunityItem objects (or duck-typed dicts).
        signals:       Sequence of raw signal dicts (headlines + jobs).
        db_path:       Path to the SQLite database.  Defaults to config.get_db_path().
    """
    if db_path is None:
        from marketscout.config import get_db_path
        db_path = get_db_path()
    db_path = Path(db_path).resolve()

    engine = create_engine(f"sqlite:///{db_path}")
    now = datetime.now(timezone.utc)

    try:
        with Session(engine) as session:
            with session.begin():
                # ── Idempotency check ─────────────────────────────────────
                if session.get(DimRun, run_id) is not None:
                    logger.debug("run_id %s already exists — skipping write_gold", run_id)
                    return

                # ── DimRun ────────────────────────────────────────────────
                session.add(DimRun(
                    id=run_id,
                    city=city,
                    industry=industry,
                    started_at=now,
                    ended_at=now,
                    signal_count=len(signals),
                ))

                # ── DimSignal (one row per raw signal) ────────────────────
                dim_signals: list[DimSignal] = []
                for sig in signals:
                    title = (sig.get("title") or "").strip()
                    url = (sig.get("link") or "").strip()
                    source = (sig.get("source") or "").strip()
                    summary = (sig.get("company") or sig.get("source") or "").strip()
                    ds = DimSignal(
                        run_id=run_id,
                        source=source,
                        title=title,
                        summary=summary,
                        url=url,
                        captured_at=_parse_dt(sig.get("published")),
                        content_hash=_content_hash(title, url),
                    )
                    session.add(ds)
                    dim_signals.append(ds)

                # Flush to get autoincrement IDs for DimSignal rows.
                session.flush()
                signal_by_url: dict[str, int] = {
                    ds.url: ds.id for ds in dim_signals if ds.url
                }

                # ── DimOpportunity + FactLead ─────────────────────────────
                for rank, opp in enumerate(opportunities, start=1):
                    pain = float(getattr(opp, "pain_score", 0) or 0)
                    roi = float(getattr(opp, "roi_signal", 0) or 0)
                    conf = float(getattr(opp, "confidence", 0) or 0)
                    evidence = list(getattr(opp, "evidence", []) or [])
                    leads_list = list(getattr(opp, "leads", []) or [])

                    company = ""
                    if leads_list:
                        company = (getattr(leads_list[0], "company_name", "") or "").strip()

                    sb = getattr(opp, "score_breakdown", None)
                    if sb is not None:
                        try:
                            sb_dict = sb.model_dump()
                        except AttributeError:
                            sb_dict = dict(sb) if hasattr(sb, "__iter__") else {}
                    else:
                        sb_dict = {}

                    dim_opp = DimOpportunity(
                        run_id=run_id,
                        company=company,
                        city=city,
                        industry=industry,
                        total_score=round((pain + roi) / 2, 3),
                        rank=rank,
                        signal_count=len(evidence),
                    )
                    session.add(dim_opp)
                    session.flush()  # get dim_opp.id before inserting FactLead

                    for ev in evidence:
                        ev_url = (getattr(ev, "link", "") or "").strip()
                        session.add(FactLead(
                            run_id=run_id,
                            opp_id=dim_opp.id,
                            signal_id=signal_by_url.get(ev_url),
                            pain_score=pain,
                            roi_score=roi,
                            confidence_score=conf,
                            score_breakdown=json.dumps(sb_dict),
                        ))
    finally:
        engine.dispose()


def get_readonly_engine(db_path: str | Path):
    """
    Return a SQLAlchemy engine backed by a read-only SQLite connection.

    Uses sqlite3 URI mode (?mode=ro) so write operations are rejected at the
    OS level regardless of what SQL is executed.
    """
    db_path = str(Path(db_path).resolve())

    def _creator() -> sqlite3.Connection:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    return create_engine("sqlite://", creator=_creator)
