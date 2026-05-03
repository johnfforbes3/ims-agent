"""
Tests for agent.notifier — Slack webhook and email notification.

Covers TD-014: notifier reads env vars at call time (not import time)
so credential rotations take effect without a process restart.
"""

import pytest


def _noop_load_dotenv(**kwargs):
    """Stub that prevents load_dotenv from re-reading .env and overriding monkeypatched vars."""


class TestNotifierHotReload:
    """TD-014 — _get_notifier_config() reads env vars at call time.

    Each test stubs ``load_dotenv`` so the real ``.env`` on disk does not
    override the env vars set by monkeypatch.  The key invariant being tested
    is that _get_notifier_config() uses os.getenv() at call time rather than
    baking values into module-level globals at import time.
    """

    def test_slack_webhook_picked_up_after_import(self, monkeypatch):
        """Changing SLACK_WEBHOOK_URL after module import takes effect immediately."""
        import agent.notifier as notifier_mod

        monkeypatch.setattr("agent.notifier.load_dotenv", _noop_load_dotenv)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test-sentinel")

        cfg = notifier_mod._get_notifier_config()
        assert cfg["slack_webhook"] == "https://hooks.slack.com/test-sentinel"

    def test_email_host_picked_up_after_import(self, monkeypatch):
        """Changing EMAIL_SMTP_HOST after module import takes effect immediately."""
        import agent.notifier as notifier_mod

        monkeypatch.setattr("agent.notifier.load_dotenv", _noop_load_dotenv)
        monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.rotated.example.com")

        cfg = notifier_mod._get_notifier_config()
        assert cfg["email_host"] == "smtp.rotated.example.com"

    def test_email_port_picked_up_after_import(self, monkeypatch):
        """Changing EMAIL_SMTP_PORT after module import takes effect immediately."""
        import agent.notifier as notifier_mod

        monkeypatch.setattr("agent.notifier.load_dotenv", _noop_load_dotenv)
        monkeypatch.setenv("EMAIL_SMTP_PORT", "465")

        cfg = notifier_mod._get_notifier_config()
        assert cfg["email_port"] == 465

    def test_dashboard_url_picked_up_after_import(self, monkeypatch):
        """Changing DASHBOARD_URL after module import takes effect immediately."""
        import agent.notifier as notifier_mod

        monkeypatch.setattr("agent.notifier.load_dotenv", _noop_load_dotenv)
        monkeypatch.setenv("DASHBOARD_URL", "https://ims.prod.example.com")

        cfg = notifier_mod._get_notifier_config()
        assert cfg["dashboard_url"] == "https://ims.prod.example.com"


class TestSendSlackSkip:
    """send_slack skips gracefully when credentials are absent."""

    def test_send_slack_returns_false_when_no_webhook(self, monkeypatch):
        """send_slack returns False and does not attempt network call without a webhook."""
        import agent.notifier as notifier_mod

        monkeypatch.setattr("agent.notifier.load_dotenv", _noop_load_dotenv)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "")

        summary = {
            "health": "GREEN",
            "top_risks": [],
            "milestones_at_risk": [],
            "cams_responded": 3,
            "cams_total": 5,
            "report_path": "reports/test.md",
            "briefing_path": None,
        }
        result = notifier_mod.send_slack(summary)
        assert result is False


class TestSendEmailSkip:
    """send_email skips gracefully when SMTP credentials are absent."""

    def test_send_email_returns_false_when_no_smtp(self, monkeypatch):
        """send_email returns False when SMTP host is not configured."""
        import agent.notifier as notifier_mod

        monkeypatch.setattr("agent.notifier.load_dotenv", _noop_load_dotenv)
        monkeypatch.setenv("EMAIL_SMTP_HOST", "")

        summary = {
            "health": "RED",
            "top_risks": ["Risk A"],
            "milestones_at_risk": [],
            "cams_responded": 2,
            "cams_total": 5,
            "report_path": "reports/test.md",
            "briefing_path": None,
        }
        result = notifier_mod.send_email(summary)
        assert result is False
