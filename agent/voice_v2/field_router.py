"""
Field router — Phase 17 iter 7.

Deterministic Python classifier that runs BEFORE the LLM on every
TASK_BY_TASK_LOOP turn. If the user's utterance matches one of three
clear field-answer patterns, we capture the field in Python without
relying on the LLM to fire the tool call.

The LLM still runs (we need its conversational reply driving the next
question), but the data extraction is no longer LLM-dependent. This is
the article's "Python is the parser" rule applied correctly — for
single-field replies that are easy to classify by regex.

Why this matters: live testing showed the LLM would say "OK. Any
risks?" without first firing capture_blocker(""), so the blocker
field stayed MISSING and the per-task tracker never advanced.

Patterns we route deterministically:
  - "<percent_number> percent" / "<word> percent" / "<percent_number>%" / "<percent_number>"
    when the missing field is percent_complete and the utterance is
    short enough to be a direct answer
  - "no blocker" / "nothing blocking" / "no issues" / "all clear" /
    "no problems" → capture_blocker with empty string
  - "no risk" / "no risks" → capture_risk(False)
  - A long-ish utterance that contains "blocker" keyword when the
    missing field is blocker → capture_blocker(verbatim)
  - "yes" / "yeah" / "yep" alone after a "any blockers?"-type question
    → leave to LLM (ambiguous)

The router returns a list of (tool_name, args) pairs that get applied
to StateContext before the LLM call, so the LLM's prompt sees the
updated field state and CAN'T re-ask.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# Word → integer for spoken percents 0..100 (covers common cases)
_WORD_TO_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}

# Patterns like "twenty-five" or "thirty five"
_COMPOUND_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
_COMPOUND_ONES = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine"}


def _strip_task_reference(text: str) -> str:
    """Remove 'task X' / 'task #X' phrases so the percent extractor doesn't
    mistake the task ID for the percent. Phase 17 iter 7 fix — live testing
    saw 'Task one is at sixty percent' route as percent=1 (the '1' from 'one').
    """
    t = re.sub(r"\btask\s+(?:id\s+)?#?(\d+|\w+)\b", " ", text, flags=re.I)
    return t


def _extract_percent(text: str) -> Optional[int]:
    """Try to pull a 0-100 integer percent from a spoken utterance.

    Returns None when no recognizable percent is present.

    Order of attempts (most specific first):
      1. "X%" / "X percent" / "X pct" with explicit unit
      2. Compound words ("sixty-five", "thirty five") + "percent" suffix or alone
      3. "at X" / "about X" / "around X" pattern with bare number/word
      4. Bare standalone number/word (only when utterance is short and clearly
         a percent answer — guarded so "task one" doesn't become 1)
      5. Special phrases ("half way", "mostly done", etc.)
    """
    if not text:
        return None
    # Strip "task N" references first so they don't pollute the search
    cleaned = _strip_task_reference(text)
    t = cleaned.lower().strip().strip(".,!?;:'\"")

    # 1. Direct numeric WITH percent unit (highest precision)
    m = re.search(r"\b(\d{1,3})\s*(?:%|percent|pct)\b", t)
    if m:
        n = int(m.group(1))
        if 0 <= n <= 100:
            return n

    # 2. Compound word ("sixty-five", "thirty five") — these are always percents
    for tens in _COMPOUND_TENS:
        for ones in _COMPOUND_ONES:
            combo = f"{tens} {ones}"
            combo_hyphen = f"{tens}-{ones}"
            if combo in t or combo_hyphen in t:
                return _WORD_TO_NUM[tens] + _WORD_TO_NUM[ones]

    # 3. Word + percent suffix ("sixty percent")
    for word, n in _WORD_TO_NUM.items():
        if re.search(rf"\b{word}\s+(?:percent|pct)\b", t):
            return n

    # 4. "at X" / "about X" / "around X" / "X complete" patterns
    at_pat = re.search(r"\b(?:at|about|around|roughly|maybe|approximately)\s+(\d{1,3}|\w+)\b", t)
    if at_pat:
        val = at_pat.group(1)
        if val.isdigit():
            n = int(val)
            if 0 <= n <= 100:
                return n
        elif val in _WORD_TO_NUM:
            return _WORD_TO_NUM[val]

    # 5. Special phrases (semantic mappings)
    if any(p in t for p in ("half way", "halfway", "about half")):
        return 50
    if any(p in t for p in ("mostly done", "almost done", "wrapping up")):
        return 80
    if any(p in t for p in ("just started", "barely started", "kicking off")):
        return 10
    if any(p in t for p in ("not started", "haven't started", "not begun")):
        return 0

    # 6. Last resort: bare standalone digit/word in a SHORT utterance.
    # Only fires when the utterance is short enough to clearly be just an
    # answer (≤ 4 words after stripping the task ref).
    words = t.split()
    if len(words) <= 4:
        m2 = re.search(r"\b(\d{1,3})\b", t)
        if m2:
            n = int(m2.group(1))
            if 0 <= n <= 100:
                return n
        for word, n in _WORD_TO_NUM.items():
            if re.search(rf"\b{word}\b", t):
                return n

    return None


# "no blocker" family
_NO_BLOCKER_PATTERNS = [
    re.compile(r"\bno\s+(blocker|blockers|issues|issue|problems|problem)\b", re.I),
    re.compile(r"\bnothing\s+(blocking|blocked)\b", re.I),
    re.compile(r"\ball\s+clear\b", re.I),
    re.compile(r"\bno\s+issues?\s+(here|right now)\b", re.I),
    re.compile(r"\bnope\b", re.I),  # short answer to "any blockers?"
]

# "no risk" family
_NO_RISK_PATTERNS = [
    re.compile(r"\bno\s+(risk|risks|concerns?)\b", re.I),
    re.compile(r"\bnothing\s+(risky|concerning)\b", re.I),
    re.compile(r"\b(all|nothing|none)\s+(good|to flag|to worry)\b", re.I),
]


def _looks_like_blocker_text(text: str) -> bool:
    """True iff the text reads like a blocker description (not a simple denial)."""
    if not text or len(text.split()) < 2:
        return False
    t = text.lower()
    return any(k in t for k in (
        "blocker", "blocked", "waiting", "delay", "stuck", "vendor",
        "procurement", "approval", "sign-off", "sign off", "hold up",
        "holding up", "pending", "still need",
    ))


def _looks_like_risk_text(text: str) -> bool:
    if not text or len(text.split()) < 3:
        return False
    t = text.lower()
    return any(k in t for k in (
        "risk", "concern", "worried", "might slip", "could slip",
        "may slip", "slip", "miss the milestone", "miss cdr", "miss pdr",
    ))


def route_field_answer(transcript: str, next_missing_field: Optional[str],
                       current_task_id: str,
                       already_captured: Optional[set] = None) -> list[tuple[str, dict]]:
    """Inspect transcript and return tool calls to fire.

    Phase 17 iter 7 — content-based routing. Earlier version only handled
    the "next missing field" which lost data when CAMs gave fields out of
    order (e.g. "The blocker is vendor delay" before stating percent).

    Now: we look at WHAT the user said and fire whichever tool(s) match.
    `next_missing_field` is used only as a tiebreaker for ambiguous percent
    extraction (a bare "60" only fires percent_complete if that's missing).
    `already_captured` (set of field names) prevents firing the same field
    twice in the same turn.

    Returns a list of (tool_name, args) tuples.
    """
    if not transcript:
        return []
    out: list[tuple[str, dict]] = []
    tid = str(current_task_id)
    already = already_captured or set()

    # 1. RISK — most distinctive keywords, check first to avoid risk text
    #    being misread as a blocker.
    if "risk_flag" not in already:
        if any(p.search(transcript) for p in _NO_RISK_PATTERNS):
            out.append(("capture_risk",
                        {"task_id": tid, "risk_flag": False, "risk_description": ""}))
        elif _looks_like_risk_text(transcript):
            out.append(("capture_risk", {
                "task_id": tid, "risk_flag": True,
                "risk_description": transcript.strip(),
            }))

    # 2. BLOCKER — check before percent since blocker text often contains
    #    numbers (e.g. "waiting on PO #1234").
    if "blocker_text" not in already:
        if any(p.search(transcript) for p in _NO_BLOCKER_PATTERNS):
            out.append(("capture_blocker", {"task_id": tid, "blocker_text": ""}))
        elif _looks_like_blocker_text(transcript):
            # Only fire if a risk hasn't already been routed for THIS message
            # (avoid double-counting "blocker is X with risk Y" as both)
            if not any(c[0] == "capture_risk" for c in out):
                out.append(("capture_blocker",
                            {"task_id": tid, "blocker_text": transcript.strip()}))

    # 3. PERCENT — last, since percent extraction can pick up numbers from
    #    blocker descriptions. Skip when blocker was just routed (to avoid
    #    routing "30 day delay" in a blocker as a percent).
    if "percent_complete" not in already:
        blocker_just_routed = any(c[0] == "capture_blocker" and c[1].get("blocker_text")
                                  for c in out)
        if not blocker_just_routed:
            n = _extract_percent(transcript)
            if n is not None:
                out.append(("propose_percent_complete",
                            {"task_id": tid, "percent_complete": n}))

    if out:
        logger.info("action=voice_field_router_fired next_missing=%s tools=%s",
                    next_missing_field, [t[0] for t in out])
    return out
