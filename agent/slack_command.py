"""
Slack slash command handler — /ims <question>

Uses slack_bolt in Socket Mode so no public URL is required.
The handler receives /ims commands, routes them through QAEngine,
and replies in-channel with a formatted answer.

Transport:
  SLACK_APP_TOKEN  — xapp-... (App-Level Token with connections:write scope)
  SLACK_BOT_TOKEN  — xoxb-... (Bot User OAuth Token with commands + chat:write scopes)

Both tokens are required. If either is missing, start() logs a warning and returns
without raising so the dashboard can still serve without Slack.

Usage:
  /ims what is the critical path?
  /ims what is Alice Nguyen behind on?
  /ims what should I focus on this week?
"""

import logging
import os
import threading

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")

_MAX_QUESTION_LEN = 400
_MAX_ANSWER_LEN = 2900  # Slack block text limit is 3000; leave headroom


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _format_answer(response) -> list[dict]:
    """Build Slack Block Kit blocks from a QAResponse."""
    answer = _truncate(response.answer, _MAX_ANSWER_LEN)
    source = f"Source: cycle `{response.source_cycle}`" if response.source_cycle else ""
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": answer},
        }
    ]
    if source:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": source}],
        })
    return blocks


def _handle_ims_command(command, ack, respond):
    """Process /ims <question> and respond in-channel."""
    ack()  # Must acknowledge within 3s

    text = (command.get("text") or "").strip()
    if not text:
        respond(
            text="Usage: `/ims <your question>`\n"
                 "Example: `/ims what are the top risks right now?`"
        )
        return

    if len(text) > _MAX_QUESTION_LEN:
        respond(text=f"Question too long (max {_MAX_QUESTION_LEN} characters).")
        return

    # Send a "thinking" message immediately, then update with the real answer
    # (slash commands require an ack within 3s; LLM calls take longer)
    respond(text=f"_Thinking about: {text}_")

    try:
        from agent.qa.qa_engine import QAEngine
        qa_response = QAEngine().ask(text)
        blocks = _format_answer(qa_response)
        respond(blocks=blocks, text=qa_response.answer[:200])
        logger.info(
            "action=slack_qa answered direct=%s intents=%s",
            qa_response.direct, qa_response.intent,
        )
    except Exception as exc:
        logger.error("action=slack_qa_error error=%s", exc, exc_info=True)
        respond(text=f":warning: Error answering question: {exc}")


def start(daemon: bool = True) -> threading.Thread | None:
    """
    Start the Slack Socket Mode handler in a background thread.

    Args:
        daemon: If True (default), thread exits when the main process exits.

    Returns:
        The started thread, or None if tokens are not configured.
    """
    if not _APP_TOKEN or not _BOT_TOKEN:
        logger.warning(
            "action=slack_command_skip reason=missing_tokens "
            "hint=set SLACK_APP_TOKEN and SLACK_BOT_TOKEN in .env"
        )
        return None

    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError:
        logger.warning(
            "action=slack_command_skip reason=slack_bolt_not_installed "
            "hint=pip install slack-bolt"
        )
        return None

    app = App(token=_BOT_TOKEN)
    app.command("/ims")(_handle_ims_command)

    handler = SocketModeHandler(app, _APP_TOKEN)

    def _run():
        logger.info("action=slack_socket_mode_start")
        try:
            handler.start()
        except Exception as exc:
            logger.error("action=slack_socket_mode_error error=%s", exc)

    thread = threading.Thread(target=_run, daemon=daemon, name="slack_socket_mode")
    thread.start()
    logger.info("action=slack_command_thread_started")
    return thread
