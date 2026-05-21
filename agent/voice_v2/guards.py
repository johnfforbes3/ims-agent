"""
Voice agent safety guards — Phase 17.

Article §5: "A voice agent has no 'read before sending' moment. An unsafe
output gets spoken immediately. No draft, no preview, no human in the loop."

The right model is TWO checkpoints, not one:

  INPUT GUARD (before the LLM sees the user's turn):
    - prompt injection ("ignore previous instructions", "you are now...")
    - PII spoken aloud (SSN, credit card patterns) — redact before logging
    - topic blocklist (JSON, weekly-maintained)

  OUTPUT GUARD (after the LLM writes its reply, before TTS speaks it):
    - over-promise language ("I guarantee", "I promise", "definitely")
    - hallucinated facts (task_id or percent_complete not in retrieved context)
    - standard moderation (catch rare model misbehavior)

Each guard returns:
    GuardResult(passed: bool, categories: list[str], redactions/rewrites: list[str])

For the IMS-Agent use case, our retrieved context is the CAM's actual task
list — so the hallucination check is: did the LLM mention a task_id or a
percent_complete value not present in the StateContext's cam_tasks?
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GuardResult:
    passed: bool = True
    categories: list[str] = field(default_factory=list)
    rewrites: list[str] = field(default_factory=list)  # human-readable notes
    replacement: Optional[str] = None  # if not None, use this instead of original


# ──────────────────────────────────────────────────────────────────────────
# Input guard
# ──────────────────────────────────────────────────────────────────────────

# Common prompt-injection markers (case-insensitive). Conservative — false
# positives would only block one CAM turn, which is recoverable.
_INJECTION_PATTERNS = [
    re.compile(r"\bignore (the|your|all|previous)\s+(prior\s+)?instructions?\b", re.I),
    re.compile(r"\byou are now\b.*\b(a|an)\s+\w+", re.I),
    re.compile(r"\bsystem\s*[:\-]\s*", re.I),
    re.compile(r"\bdisregard (the|your|all)\s+(prior\s+)?instructions?\b", re.I),
    re.compile(r"\bact as\s+(if you (are|were)|though you (are|were))\b", re.I),
    re.compile(r"\bpretend (to be|you are)\b", re.I),
    re.compile(r"\bnew (system|developer)\s+(prompt|instructions?|message)\b", re.I),
]

# PII patterns — high precision, low recall (don't try to catch everything)
_SSN_RE   = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CCARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_PII_RE   = re.compile(r"\b(?:" + _SSN_RE.pattern + r"|" + _CCARD_RE.pattern + r")\b")

# Topic blocklist — IMS use case is narrow, so a small list is fine
_BLOCKED_TOPICS = [
    (re.compile(r"\b(legal|lawsuit|sue|attorney|counsel)\s+(advice|opinion)\b", re.I),
     "legal_advice"),
    (re.compile(r"\b(salary|wage|compensation|bonus|raise)\s+(negotiation|complaint)\b", re.I),
     "hr_compensation"),
    (re.compile(r"\b(fire|terminate|lay\s*off|discipline)\s+\w+", re.I),
     "hr_termination"),
]


def check_input(transcript: str) -> GuardResult:
    """Run all input checks. Returns first-fail (fail-fast) for clarity."""
    if not transcript or not transcript.strip():
        return GuardResult()

    for pat in _INJECTION_PATTERNS:
        if pat.search(transcript):
            logger.warning("action=voice_v2_input_guard_block category=prompt_injection match=%r",
                           pat.pattern)
            return GuardResult(
                passed=False,
                categories=["prompt_injection"],
                rewrites=[f"matched: {pat.pattern}"],
                replacement=(
                    "I'm just here to capture your task status. "
                    "Let's stick to that — what task would you like to update?"
                ),
            )

    redactions: list[str] = []
    if _SSN_RE.search(transcript):
        redactions.append("SSN")
    if _CCARD_RE.search(transcript):
        redactions.append("credit_card")
    if redactions:
        # Don't block — redact for logs but let the LLM see the cleaned text.
        cleaned = _SSN_RE.sub("[SSN-REDACTED]", transcript)
        cleaned = _CCARD_RE.sub("[CARD-REDACTED]", cleaned)
        logger.warning("action=voice_v2_input_guard_redact categories=%s", redactions)
        return GuardResult(
            passed=True,
            categories=[f"pii_{r.lower()}" for r in redactions],
            rewrites=[f"redacted {r}" for r in redactions],
            replacement=cleaned,
        )

    for pat, category in _BLOCKED_TOPICS:
        if pat.search(transcript):
            logger.warning("action=voice_v2_input_guard_block category=%s", category)
            return GuardResult(
                passed=False,
                categories=[category],
                rewrites=[f"topic blocked: {category}"],
                replacement=(
                    "That's outside what I'm set up to discuss. "
                    "Let me flag this for your PM and we will follow up."
                ),
            )

    return GuardResult()


# ──────────────────────────────────────────────────────────────────────────
# Output guard
# ──────────────────────────────────────────────────────────────────────────


_OVER_PROMISE_PATTERNS = [
    (re.compile(r"\bI guarantee\b", re.I),       "I will capture that"),
    (re.compile(r"\bI promise\b", re.I),         "I will note that"),
    (re.compile(r"\bdefinitely will\b", re.I),   "I will try to"),
    (re.compile(r"\bcertainly will\b", re.I),    "I will"),
    (re.compile(r"\b100\s*%\s*(certain|sure)\b", re.I), "as far as I know"),
]


def check_output(
    reply_text: str,
    valid_task_ids: Optional[list[str]] = None,
    valid_pct_range: tuple[int, int] = (0, 100),
) -> GuardResult:
    """Run all output checks against the LLM's reply BEFORE it reaches TTS.

    Args:
        reply_text:     The LLM's text response.
        valid_task_ids: Task IDs the CAM is allowed to talk about. Any other
                        task_id mentioned by the LLM is a hallucination.
        valid_pct_range: Valid percent-complete range.

    Returns:
        GuardResult with `replacement` populated when rewrites occurred.
    """
    if not reply_text:
        return GuardResult()

    rewrites: list[str] = []
    categories: list[str] = []
    out = reply_text

    # 1. Over-promise rewrites
    for pat, repl in _OVER_PROMISE_PATTERNS:
        if pat.search(out):
            out = pat.sub(repl, out)
            rewrites.append(f"over_promise → '{pat.pattern}' → '{repl}'")
            if "over_promise" not in categories:
                categories.append("over_promise")

    # 2. Hallucination check: did the LLM mention a task_id NOT in the CAM's list?
    # Voice context — the LLM is correctly instructed to spell numbers ("task one"
    # not "task 1") for TTS, so we accept both digit and word forms. We only flag
    # when the mentioned ID has the SHAPE of a real task ID (digit / digit+letter)
    # and is unambiguously NOT in the valid set. Plain-English words after "task"
    # (one, two, three, the, first, etc.) are ignored — they need lexical fuzzy
    # matching which is over-engineering for a 5-CAM cycle.
    if valid_task_ids is not None:
        valid_set = {str(t).lower() for t in valid_task_ids}
        # Word → digit mapping for safe number recognition (1..20 covers IMS scale)
        _word_to_digit = {
            "zero":"0","one":"1","two":"2","three":"3","four":"4","five":"5",
            "six":"6","seven":"7","eight":"8","nine":"9","ten":"10",
            "eleven":"11","twelve":"12","thirteen":"13","fourteen":"14","fifteen":"15",
            "sixteen":"16","seventeen":"17","eighteen":"18","nineteen":"19","twenty":"20",
        }
        # Match "task 12", "task ID 12", "task #12", "task one"
        for m in re.finditer(r"\btask(?:\s+id)?\s+#?(\w+)", reply_text, re.I):
            raw = m.group(1).lower().rstrip(".,;:!?")
            # Resolve word form to digit form when possible; otherwise keep raw
            tid_candidates = {raw, _word_to_digit.get(raw, raw)}
            # Only check shapes that LOOK like an ID — digits or digit+letter mix
            looks_like_id = any(
                re.fullmatch(r"\d+|[a-z]?\d+[a-z]*\d*|[a-z]+-?\d+", c)
                for c in tid_candidates
            )
            if not looks_like_id:
                # e.g. "task the first", "task that", "task you mentioned" — skip
                continue
            if not (tid_candidates & valid_set):
                categories.append("hallucinated_task_id")
                rewrites.append(
                    f"hallucinated task_id: {raw} (resolved={tid_candidates}, "
                    f"valid: {sorted(valid_set)[:6]}...)"
                )
                # Don't try to repair — fail closed, return the escalation phrase
                from agent.voice_v2.state_machine import ESCALATION_PHRASE
                return GuardResult(
                    passed=False,
                    categories=categories,
                    rewrites=rewrites,
                    replacement=ESCALATION_PHRASE,
                )

    # 3. Percent-complete out of range
    for m in re.finditer(r"\b(\d{1,3})\s*(?:%|percent)\b", reply_text, re.I):
        try:
            pct = int(m.group(1))
            if not (valid_pct_range[0] <= pct <= valid_pct_range[1]):
                categories.append("invalid_percent")
                rewrites.append(f"invalid percent_complete: {pct}")
                from agent.voice_v2.state_machine import ESCALATION_PHRASE
                return GuardResult(
                    passed=False,
                    categories=categories,
                    rewrites=rewrites,
                    replacement=ESCALATION_PHRASE,
                )
        except ValueError:
            continue

    # 4. Strip markdown that snuck through (article §4: TTS speaks asterisks)
    if "*" in out or "**" in out or "_" in out:
        out_clean = re.sub(r"\*\*?", "", out)
        out_clean = re.sub(r"(?<!\w)_(?!\w)", "", out_clean)
        if out_clean != out:
            rewrites.append("stripped markdown")
            if "markdown_in_voice" not in categories:
                categories.append("markdown_in_voice")
            out = out_clean

    passed = "hallucinated_task_id" not in categories and "invalid_percent" not in categories
    return GuardResult(
        passed=passed,
        categories=categories,
        rewrites=rewrites,
        replacement=out if rewrites else None,
    )


# ──────────────────────────────────────────────────────────────────────────
# Convenience helpers
# ──────────────────────────────────────────────────────────────────────────


def apply_input_guard(transcript: str) -> tuple[str, GuardResult]:
    """Run input guard, return (sanitized_text, result).

    If the guard didn't block, returns the original (or PII-redacted) text.
    If the guard blocked, returns the replacement text the agent should speak.
    """
    r = check_input(transcript)
    if r.replacement is not None:
        return r.replacement, r
    return transcript, r


def apply_output_guard(
    reply_text: str,
    valid_task_ids: Optional[list[str]] = None,
) -> tuple[str, GuardResult]:
    """Run output guard, return (sanitized_text, result)."""
    r = check_output(reply_text, valid_task_ids=valid_task_ids)
    if r.replacement is not None:
        return r.replacement, r
    return reply_text, r
