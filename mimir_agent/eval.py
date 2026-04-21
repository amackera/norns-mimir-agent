"""Thread classification and eval record management."""

import json
import logging
import random

import anthropic

from mimir_agent import config, db

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT = """\
You are classifying the outcome of a Q&A thread. You'll see the original \
question, the bot's answer, and any follow-up messages in the thread.

Classify the outcome as one of:
- explicit_success: positive reaction, thanks, "that worked", user confirmed it helped
- implicit_success: thread went quiet after the answer, no contradiction
- disagreement: competing human answer, negative reaction, user kept asking the same thing, correction posted
- ambiguous: thread continued but direction is unclear

Return JSON: {"outcome": "...", "evidence": "one sentence why", "confidence": 0.0-1.0}
Nothing else."""


def classify_thread(question: str, answer: str, follow_ups: list[str]) -> dict:
    """Classify a thread outcome using an LLM call. Returns {outcome, evidence, confidence}."""
    thread_text = f"Question: {question}\n\nBot answer: {answer}"
    if follow_ups:
        thread_text += "\n\nFollow-up messages:\n" + "\n".join(f"- {m}" for m in follow_ups)
    else:
        thread_text += "\n\n(No follow-up messages — thread went quiet)"

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        system=CLASSIFY_PROMPT,
        messages=[{"role": "user", "content": thread_text}],
    )

    try:
        return json.loads(resp.content[0].text)
    except (json.JSONDecodeError, IndexError):
        return {"outcome": "ambiguous", "evidence": "Classification failed to parse", "confidence": 0.0}


def classify_and_store(thread_ref: str, follow_ups: list[str]) -> dict | None:
    """Classify a thread and persist the result."""
    record = db.get_eval_record(thread_ref)
    if not record:
        return None

    result = classify_thread(record["question"], record["answer"], follow_ups)
    db.classify_eval_record(
        thread_ref,
        result["outcome"],
        result["evidence"],
        result["confidence"],
    )
    logger.info("Classified %s: %s (%.2f)", thread_ref, result["outcome"], result["confidence"])
    return result


# --- Solicited feedback ---

FEEDBACK_SAMPLE_RATE = 0.05  # 5% of classified threads
MAX_DMS_PER_USER_PER_WEEK = 1


def should_solicit_feedback() -> bool:
    """Uniform random 5% sampling."""
    return random.random() < FEEDBACK_SAMPLE_RATE


def build_feedback_dm(question: str, answer: str) -> str:
    """Build the DM template for solicited feedback."""
    q_short = question[:100] + "..." if len(question) > 100 else question
    a_short = answer[:100] + "..." if len(answer) > 100 else answer
    return (
        f"Earlier you asked: \"{q_short}\"\n"
        f"I answered: \"{a_short}\"\n\n"
        "Did that end up being helpful?\n"
        "Reply: yes / no / partially. Optional: what was wrong?"
    )
