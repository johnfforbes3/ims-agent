"""
Small-talk gate — Phase 17 iteration 2.

Article §11 #6: "Build the small-talk gate before you build retrieval.
'Hi' is the cheapest 200ms win in the system."

For the GREETING state, we don't need an LLM call at all — the response is
deterministic. We just need to detect that the user gave a greeting (vs
diving straight into content) and respond with a hardcoded template.

This saves:
    - ~$0.0001 per greeting turn (LLM call cost)
    - ~600-2000ms per greeting turn (LLM round-trip)
    - One spend-cap charge

For non-greeting OPEN_QUESTION turns, we still use the LLM.

Implementation: pipeline checks `is_small_talk_greeting(transcript)` at
the start of a GREETING state turn. If true → return a hardcoded greeting
keyed to the CAM's first name + task count. Otherwise → fall through to
the normal LLM path.
"""

from __future__ import annotations

import re

# Phrases that mean "hi, I'm here" with no status content. Order doesn't matter.
# Each phrase is matched as a whole-utterance regex (case-insensitive) — we
# want false negatives, NOT false positives, since a false negative just runs
# the LLM (paying a turn) while a false positive skips a real status update.
_GREETING_PATTERNS = [
    re.compile(r"^\s*(hi|hello|hey|howdy)[\s,.!]*$", re.I),
    re.compile(r"^\s*(hi|hello|hey),?\s+this is\s+\w+[\s,.!]*$", re.I),
    re.compile(r"^\s*(hi|hello|hey),?\s+(it'?s|its)\s+\w+[\s,.!]*$", re.I),
    re.compile(r"^\s*(hi|hello|hey)\s+(there|atlas)[\s,.!]*$", re.I),
    re.compile(r"^\s*good\s+(morning|afternoon|evening)[\s,.!]*$", re.I),
    re.compile(r"^\s*good\s+(morning|afternoon|evening),?\s+\w+[\s,.!]*$", re.I),
    re.compile(r"^\s*\w+\s+here[\s,.!]*$", re.I),  # "Alice here."
    re.compile(r"^\s*this\s+is\s+\w+[\s,.!]*$", re.I),  # "This is Alice."
]


def is_small_talk_greeting(transcript: str) -> bool:
    """True iff the transcript is a simple greeting with no status content."""
    if not transcript or not transcript.strip():
        return False
    t = transcript.strip()
    # Quick reject: longer than 10 words is definitely not small talk
    if len(t.split()) > 10:
        return False
    return any(p.match(t) for p in _GREETING_PATTERNS)


def greeting_reply(cam_first_name: str, task_count: int) -> str:
    """Deterministic greeting matched to context. No LLM call."""
    name = cam_first_name.strip().split()[0] if cam_first_name else "there"
    if task_count == 0:
        return (
            f"Hi {name}. I do not have any tasks to cover with you this week. "
            f"You are all set."
        )
    if task_count == 1:
        return (
            f"Hi {name}. I have one task to go through with you today. "
            f"Is now a good time?"
        )
    # spell out small counts; for larger, use the digit
    words = ["zero","one","two","three","four","five","six","seven","eight","nine","ten"]
    count_word = words[task_count] if task_count < len(words) else str(task_count)
    return (
        f"Hi {name}. I have {count_word} tasks to walk through with you. "
        f"Is now a good time?"
    )


# Acknowledgment-only utterances: short, no content, just "OK" / "ready" / "sure"
_READY_PATTERNS = [
    re.compile(r"^\s*(ok|okay|sure|yes|yeah|yep|ready|go|let'?s go|let's begin|let us begin)[\s,.!]*$", re.I),
    re.compile(r"^\s*(i'?m|i am)\s+(ready|good|set)[\s,.!]*$", re.I),
    re.compile(r"^\s*(yes|yeah|yep|sure),?\s+(ready|let'?s go|go ahead)[\s,.!]*$", re.I),
    re.compile(r"^\s*go ahead[\s,.!]*$", re.I),
    re.compile(r"^\s*(now is|now's)\s+(fine|good)[\s,.!]*$", re.I),
]


def is_ready_acknowledgment(transcript: str) -> bool:
    """True iff the user is just saying 'OK, ready to start' with no content."""
    if not transcript or not transcript.strip():
        return False
    t = transcript.strip()
    if len(t.split()) > 8:
        return False
    return any(p.match(t) for p in _READY_PATTERNS)


def open_question_reply(task_name: str) -> str:
    """Deterministic 'let's start' transition reply."""
    return (
        f"Great. Let's start with {task_name}. "
        f"What is your current percent complete?"
    )
