"""
Notifier — Slack webhook and email (SMTP) output for cycle completion.

Both channels are optional; if credentials are not configured the
send functions log a skip and return False without raising.
"""

import json
import logging
import os
import smtplib
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "")
_EMAIL_HOST = os.getenv("EMAIL_SMTP_HOST", "")
_EMAIL_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
_EMAIL_USER = os.getenv("EMAIL_SMTP_USER", "")
_EMAIL_PASS = os.getenv("EMAIL_SMTP_PASS", "")
_EMAIL_FROM = os.getenv("EMAIL_FROM", "")
_EMAIL_TO = os.getenv("EMAIL_TO", "")
_DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:9000")


def build_cycle_summary(
    health: str,
    top_risks: list[str],
    milestones_at_risk: list[dict],
    cams_responded: int,
    cams_total: int,
    report_path: str,
    briefing_path: str | None = None,
) -> dict[str, Any]:
    return {
        "health": health,
        "top_risks": top_risks,
        "milestones_at_risk": milestones_at_risk,
        "cams_responded": cams_responded,
        "cams_total": cams_total,
        "report_path": report_path,
        "briefing_path": briefing_path,
    }


def send_slack(summary: dict[str, Any]) -> bool:
    """Post a structured cycle summary to the configured Slack webhook."""
    if not _SLACK_WEBHOOK:
        logger.info("action=slack_skip reason=no_webhook_configured")
        return False

    health = summary.get("health", "UNKNOWN").upper()
    emoji = {"RED": ":red_circle:", "YELLOW": ":large_yellow_circle:", "GREEN": ":large_green_circle:"}.get(health, ":white_circle:")
    cams_responded = summary.get("cams_responded", 0)
    cams_total = summary.get("cams_total", 0)
    risks = summary.get("top_risks", [])
    risks_text = "\n".join(f"• {r[:120]}" for r in risks[:3]) if risks else "_None identified_"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"IMS Agent Cycle Complete {emoji}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Schedule Health:*\n{emoji} {health}"},
                {"type": "mrkdwn", "text": f"*CAM Response Rate:*\n{cams_responded}/{cams_total}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Top Risks:*\n{risks_text}"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Dashboard"},
                    "url": _DASHBOARD_URL,
                    "style": "primary",
                }
            ],
        },
    ]

    payload = json.dumps({"blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        _SLACK_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.info("action=slack_sent")
                return True
            logger.warning("action=slack_error status=%d", resp.status)
            return False
    except Exception as exc:
        logger.error("action=slack_exception error=%s", exc)
        return False


def send_email(summary: dict[str, Any]) -> bool:
    """Send a cycle summary email via SMTP to the configured distribution list."""
    if not all([_EMAIL_HOST, _EMAIL_USER, _EMAIL_PASS, _EMAIL_FROM, _EMAIL_TO]):
        logger.info("action=email_skip reason=no_smtp_configured")
        return False

    health = summary.get("health", "UNKNOWN").upper()
    risks = summary.get("top_risks", [])
    cams_responded = summary.get("cams_responded", 0)
    cams_total = summary.get("cams_total", 0)
    report_path = summary.get("report_path", "N/A")

    health_color = {"RED": "#d93025", "YELLOW": "#f9ab00", "GREEN": "#1e8e3e"}.get(health, "#666")
    risks_html = "".join(f"<li>{r}</li>" for r in risks[:3]) or "<li>None identified</li>"

    subject = f"[IMS Agent] Schedule Cycle Complete — Health: {health}"
    body_html = f"""
<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
  <h2 style="color:#333">IMS Agent — Schedule Status Cycle</h2>
  <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
    <tr>
      <td style="padding:12px;background:#f8f9fa;border:1px solid #e0e0e0">
        <strong>Schedule Health</strong><br>
        <span style="font-size:20px;font-weight:bold;color:{health_color}">{health}</span>
      </td>
      <td style="padding:12px;background:#f8f9fa;border:1px solid #e0e0e0">
        <strong>CAM Response Rate</strong><br>
        <span style="font-size:20px">{cams_responded}/{cams_total}</span>
      </td>
    </tr>
  </table>
  <h3>Top Risks</h3>
  <ul style="line-height:1.6">{risks_html}</ul>
  <p>
    <a href="{_DASHBOARD_URL}"
       style="background:#1a73e8;color:white;padding:10px 20px;text-decoration:none;border-radius:4px">
      View Live Dashboard
    </a>
  </p>
  <p style="color:#888;font-size:12px">Full report: {report_path}</p>
</body></html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _EMAIL_FROM
    msg["To"] = _EMAIL_TO
    msg.attach(MIMEText(body_html, "html"))

    recipients = [r.strip() for r in _EMAIL_TO.split(",") if r.strip()]
    try:
        with smtplib.SMTP(_EMAIL_HOST, _EMAIL_PORT) as smtp:
            smtp.starttls()
            smtp.login(_EMAIL_USER, _EMAIL_PASS)
            smtp.sendmail(_EMAIL_FROM, recipients, msg.as_string())
        logger.info("action=email_sent recipients=%d", len(recipients))
        return True
    except Exception as exc:
        logger.error("action=email_exception error=%s", exc)
        return False
