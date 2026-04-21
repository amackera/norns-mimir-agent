import logging

from norns import Norns, Agent

from mimir_agent import config
from mimir_agent.tools import all_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

SYSTEM_PROMPT = """\
You are Mimir, a product knowledge assistant. Answer questions by searching \
available knowledge sources. Be extremely brief — one or two sentences when \
possible. Never explain your process, what you searched, or offer follow-ups \
the user didn't ask for. Just give the answer.

Before answering, always search_memory first. Then search other sources if \
needed. Never say "I don't have information" without searching first.

When the user says "remember this", store their exact words — especially URLs \
and identifiers. Use descriptive keys (e.g. "norns_repo_url"). Before storing, \
check search_memory for duplicates and reuse existing keys.

For release notes, use draft_release_notes (not search_github). For designs, \
use search_figma then render_figma_frame.

Always do tool calls first, then respond in a separate message. Cite sources \
briefly (file path or doc name).

Formatting: use Slack mrkdwn. *bold*, _italic_, <url|label> for links. \
Never wrap URLs in underscores or other formatting. Use dashes for lists.
"""

def _build_sources_section() -> str:
    """Build a dynamic section listing connected knowledge sources."""
    from mimir_agent import db
    sources = db.list_sources()
    lines = ["\nConnected sources:"]
    for source_type, identifier, label in sources:
        entry = f"- {source_type}: {identifier}"
        if label:
            entry += f" ({label})"
        lines.append(entry)
    lines.append("- Memory: Postgres with semantic vector search")
    lines.append("- Web: can fetch any URL on demand")
    if not sources:
        lines.append("No external sources connected yet. Users can add them with connect_source.")
    return "\n".join(lines)


def _build_onboarding_section() -> str:
    from mimir_agent import db
    count = db.memory_count()
    sources = db.list_sources()

    if count == 0 and not sources:
        return """
Onboarding: this is a fresh instance with no memories or sources. On the \
user's first message, briefly introduce yourself in one sentence and ask \
what product or project you should learn about. Suggest they connect a \
GitHub repo (e.g. "connect repo owner/name") or share a link for you to read."""

    if count < 5:
        return """
Onboarding: this instance is still new. After answering a question, you may \
occasionally (not every time) mention one capability the user hasn't tried \
yet — like sharing a URL, connecting a repo, or asking about designs. Keep \
it to a single short sentence, and only if it's relevant to what they asked."""

    return ""


def _build_system_prompt() -> str:
    return SYSTEM_PROMPT + _build_sources_section() + _build_onboarding_section()


def main():
    from mimir_agent import db
    db.init()

    agent = Agent(
        name="mimir-agent",
        model="claude-sonnet-4-20250514",
        system_prompt=_build_system_prompt(),
        tools=all_tools,
        mode="conversation",
        max_steps=40,
        on_failure="retry_last_step",
    )

    norns = Norns(config.NORNS_URL, api_key=config.NORNS_API_KEY)
    norns.run(agent)


if __name__ == "__main__":
    main()
