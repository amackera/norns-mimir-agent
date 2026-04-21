import logging
import re
import time
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from norns import NornsClient

from mimir_agent import config, db
from mimir_agent.eval import classify_and_store, should_solicit_feedback, build_feedback_dm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("mimir_agent.slack")

app = App(token=config.SLACK_BOT_TOKEN)
norns_client = NornsClient(config.NORNS_URL, api_key=config.NORNS_API_KEY)
_bot_user_id: str | None = None

# Observation state for eval
# {thread_ts: {"channel", "question", "answer", "asker", "timer", "follow_ups"}}
_observed_threads: dict[str, dict] = {}
_observed_lock = threading.Lock()
_dm_sent: dict[str, float] = {}  # user_id -> last DM unix timestamp

OBSERVATION_TIMEOUT = 24 * 60 * 60  # 24 hours
DM_COOLDOWN = 7 * 24 * 60 * 60  # 1 week


def to_slack_mrkdwn(text: str) -> str:
    """Convert common Markdown patterns to Slack mrkdwn.

    Slack supports *bold* and _italic_, not Markdown **bold**.
    """
    if not text:
        return text

    out = text

    # Convert links: [text](url) -> <url|text>
    out = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"<\2|\1>", out)

    # Convert headings to bold lines
    out = re.sub(r"(?m)^\s*#{1,6}\s+(.+)$", r"*\1*", out)

    # Convert markdown bold/italic to Slack style
    out = re.sub(r"\*\*(.+?)\*\*", r"*\1*", out)
    out = re.sub(r"__(.+?)__", r"*\1*", out)
    out = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"_\1_", out)

    # Normalize list bullets to a cleaner glyph
    out = re.sub(r"(?m)^\s*[-*]\s+", "• ", out)

    # Keep output readable in Slack mobile
    out = re.sub(r"\n{3,}", "\n\n", out).strip()

    return out


# --- Eval observation ---

def _start_observation(thread_ts: str, channel: str, question: str, answer: str, asker: str):
    """Begin observing a thread for eval classification."""
    db.create_eval_record(thread_ts, channel, question, answer, asker)

    timer = threading.Timer(OBSERVATION_TIMEOUT, _on_observation_timeout, args=[thread_ts])
    timer.daemon = True
    timer.start()

    with _observed_lock:
        _observed_threads[thread_ts] = {
            "channel": channel,
            "question": question,
            "answer": answer,
            "asker": asker,
            "timer": timer,
            "follow_ups": [],
        }
    logger.info("Observing thread %s for eval", thread_ts)


def _on_thread_activity(thread_ts: str, user: str, text: str):
    """Called when a non-bot message appears in an observed thread."""
    with _observed_lock:
        obs = _observed_threads.get(thread_ts)
        if not obs:
            return
        obs["follow_ups"].append(f"@{user}: {text}")

        # Reset the timer — give more time after activity
        obs["timer"].cancel()
        timer = threading.Timer(OBSERVATION_TIMEOUT, _on_observation_timeout, args=[thread_ts])
        timer.daemon = True
        timer.start()
        obs["timer"] = timer


def _on_observation_timeout(thread_ts: str):
    """Timer expired — classify the thread."""
    with _observed_lock:
        obs = _observed_threads.pop(thread_ts, None)
    if not obs:
        return

    follow_ups = obs["follow_ups"]
    try:
        result = classify_and_store(thread_ts, follow_ups)
        if result and should_solicit_feedback():
            _maybe_send_feedback_dm(thread_ts, obs)
    except Exception as e:
        logger.error("Classification failed for %s: %s", thread_ts, e)


def _on_negative_reaction(thread_ts: str):
    """Explicit contradiction signal — classify immediately as likely disagreement."""
    with _observed_lock:
        obs = _observed_threads.pop(thread_ts, None)
    if not obs:
        return

    obs["timer"].cancel()
    try:
        classify_and_store(thread_ts, obs["follow_ups"])
    except Exception as e:
        logger.error("Classification failed for %s: %s", thread_ts, e)


def _maybe_send_feedback_dm(thread_ts: str, obs: dict):
    """Send a feedback DM if the user hasn't been DMed recently."""
    asker = obs["asker"]
    if not asker:
        return

    now = time.time()
    last_dm = _dm_sent.get(asker, 0)
    if now - last_dm < DM_COOLDOWN:
        return

    try:
        dm_text = build_feedback_dm(obs["question"], obs["answer"])
        # Open a DM channel with the user
        dm = app.client.conversations_open(users=[asker])
        dm_channel = dm["channel"]["id"]
        app.client.chat_postMessage(
            channel=dm_channel,
            text=dm_text,
            metadata={
                "event_type": "mimir_feedback",
                "event_payload": {"thread_ref": thread_ts},
            },
        )
        _dm_sent[asker] = now
        logger.info("Sent feedback DM to %s for thread %s", asker, thread_ts)
    except Exception as e:
        logger.error("Failed to send feedback DM: %s", e)


# --- Slack event handlers ---

def handle_mention(body, say, client):
    """Handle @mentions — always respond."""
    _handle(body, say, client)


def handle_message(body, say, client):
    """Handle regular messages — only respond in DMs or threads we're already in."""
    global _bot_user_id
    event = body["event"]

    # Skip bot messages to avoid loops
    if event.get("bot_id") or event.get("subtype"):
        return

    # Check for feedback DM responses
    if event.get("channel_type") == "im":
        if _handle_feedback_response(event):
            return
        _handle(body, say, client)
        return

    # Track thread activity for eval observation
    thread_ts = event.get("thread_ts")
    if thread_ts and thread_ts in _observed_threads:
        user = event.get("user", "")
        text = event.get("text", "")
        if user != _bot_user_id:
            _on_thread_activity(thread_ts, user, text)

    # In channels, only respond to thread replies (not top-level messages)
    if not thread_ts:
        return

    # Check if we've already replied in this thread
    try:
        if _bot_user_id is None:
            _bot_user_id = client.auth_test()["user_id"]

        replies = client.conversations_replies(
            channel=event["channel"], ts=thread_ts, limit=20
        )
        bot_in_thread = any(
            msg.get("user") == _bot_user_id for msg in replies.get("messages", [])
        )
        if not bot_in_thread:
            return
    except Exception:
        return

    _handle(body, say, client)


def _handle(body, say, client):
    event = body["event"]

    # Skip bot messages to avoid loops
    if event.get("bot_id") or event.get("subtype"):
        return

    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    user_text = event.get("text", "")

    # Strip bot mention
    user_text = re.sub(r"<@\w+>", "", user_text).strip()
    if not user_text:
        return

    conversation_key = f"slack:{channel}:{thread_ts}"

    # Add thinking reaction
    try:
        client.reactions_add(channel=channel, timestamp=event["ts"], name="thinking_face")
    except Exception:
        pass

    try:
        result = norns_client.send_message(
            "mimir-agent",
            user_text,
            conversation_key=conversation_key,
            wait=True,
            timeout=120,
        )

        # Remove thinking reaction
        try:
            client.reactions_remove(channel=channel, timestamp=event["ts"], name="thinking_face")
        except Exception:
            pass

        if result.output:
            say(text=to_slack_mrkdwn(result.output), thread_ts=thread_ts)
            _start_observation(thread_ts, channel, user_text, result.output, event.get("user", ""))
        elif result.status == "completed":
            say(text="Done — but I didn't have anything to add beyond what I found.", thread_ts=thread_ts)
        else:
            say(text=f"Sorry, something went wrong (status: {result.status}).", thread_ts=thread_ts)

    except TimeoutError:
        try:
            client.reactions_remove(channel=channel, timestamp=event["ts"], name="thinking_face")
        except Exception:
            pass
        say(text="Sorry, that took too long. Please try again.", thread_ts=thread_ts)

    except Exception as e:
        logger.error(f"Error handling message: {e}")
        try:
            client.reactions_remove(channel=channel, timestamp=event["ts"], name="thinking_face")
        except Exception:
            pass
        say(text="Sorry, something went wrong.", thread_ts=thread_ts)


def handle_reaction(body, client):
    """Handle reactions — negative reactions trigger early classification."""
    event = body["event"]
    reaction = event.get("reaction", "")
    if reaction not in ("-1", "thumbsdown", "x", "no_entry"):
        return

    # Find the thread this reaction belongs to
    item = event.get("item", {})
    ts = item.get("ts", "")
    # Check if this message is in an observed thread
    with _observed_lock:
        if ts in _observed_threads:
            _on_negative_reaction(ts)


def _handle_feedback_response(event: dict) -> bool:
    """Check if a DM is a response to a feedback request. Returns True if handled."""
    text = event.get("text", "").strip().lower()
    user = event.get("user", "")
    if not text or not user:
        return False

    # Look for recent eval records from this user that are awaiting feedback
    candidates = db.get_feedback_candidates(limit=50)
    for record in candidates:
        if record["asker"] == user:
            db.record_feedback(record["thread_ref"], event.get("text", "").strip())
            logger.info("Recorded feedback from %s for thread %s", user, record["thread_ref"])
            try:
                app.client.chat_postMessage(
                    channel=event["channel"],
                    text="Thanks for the feedback!",
                )
            except Exception:
                pass
            return True

    return False


app.event("app_mention")(handle_mention)
app.event("message")(handle_message)
app.event("reaction_added")(handle_reaction)


def main():
    if not config.SLACK_BOT_TOKEN or not config.SLACK_APP_TOKEN:
        raise RuntimeError("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set")
    logger.info("Starting Mimir Slack bot")
    handler = SocketModeHandler(app, config.SLACK_APP_TOKEN)
    handler.start()


if __name__ == "__main__":
    main()
