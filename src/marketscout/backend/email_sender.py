"""Email briefing sender: plain-text run summary via Gmail SMTP / STARTTLS.

Config is read from marketscout.config.get_smtp_config() — never from os.environ directly.
send_briefing() never raises; it always returns (sent: bool, detail: str).
"""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from typing import Any

from marketscout.config import get_smtp_config

_GMAIL_HOST = "smtp.gmail.com"
_GMAIL_PORT = 587


def _build_body(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (subject, body) for the briefing email."""
    run_id = payload.get("run_id", "")
    city = payload.get("city", "")
    industry = payload.get("industry", "")
    opps = payload.get("opportunities") or []

    subject = f"MarketScout Briefing — {city} | {industry} (run {run_id})"

    lines = [
        f"MarketScout Briefing",
        f"City: {city}  |  Industry: {industry}  |  Run ID: {run_id}",
        f"Opportunities: {len(opps)}",
        "",
        "── Ranked Opportunities ──────────────────────────────",
    ]

    for rank, opp in enumerate(opps, start=1):
        if isinstance(opp, dict):
            title = opp.get("title", "(untitled)")
            pain = opp.get("pain_score", 0)
            roi = opp.get("roi_signal", 0)
            conf = opp.get("confidence", 0)
        else:
            title = getattr(opp, "title", "(untitled)")
            pain = getattr(opp, "pain_score", 0)
            roi = getattr(opp, "roi_signal", 0)
            conf = getattr(opp, "confidence", 0)

        try:
            conf_str = f"{float(conf):.2f}"
        except (TypeError, ValueError):
            conf_str = str(conf)

        lines.append(f"{rank:2d}. {title}")
        lines.append(f"    pain={pain}  roi={roi}  confidence={conf_str}")

    lines += ["", "── End of Briefing ───────────────────────────────────", "Sent by MarketScout."]
    return subject, "\n".join(lines)


def send_briefing(payload: dict[str, Any]) -> tuple[bool, str]:
    """
    Build and send a plain-text briefing email.

    Returns:
        (True, success_message)   on success.
        (False, error_message)    on missing config or SMTP failure — never raises.
    """
    cfg = get_smtp_config()
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        keys = ", ".join(k.upper() for k in missing)
        return False, f"SMTP not configured — missing environment variables: {keys}"

    subject, body = _build_body(payload)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["smtp_user"]
    msg["To"] = cfg["briefing_recipient"]

    try:
        with smtplib.SMTP(_GMAIL_HOST, _GMAIL_PORT) as server:
            server.starttls()
            server.login(cfg["smtp_user"], cfg["smtp_app_password"])
            server.sendmail(cfg["smtp_user"], cfg["briefing_recipient"], msg.as_string())
        return True, f"Briefing sent to {cfg['briefing_recipient']}."
    except Exception as exc:
        return False, f"SMTP error: {exc}"
