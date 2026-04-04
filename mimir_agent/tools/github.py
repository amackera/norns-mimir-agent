from github import Github, GithubException

from norns import tool

from mimir_agent import config


def _get_client() -> Github:
    if not config.GITHUB_TOKEN:
        raise ValueError("GitHub integration is not configured (GITHUB_TOKEN missing)")
    return Github(config.GITHUB_TOKEN)


@tool
def search_github(query: str, repo: str = "") -> str:
    """Search code and issues in connected GitHub repos. Optionally filter to a specific repo (owner/repo format)."""
    try:
        g = _get_client()
    except ValueError as e:
        return str(e)

    repos = [repo] if repo else config.GITHUB_REPOS
    if not repos:
        return "No GitHub repos configured. Set GITHUB_REPOS in your environment."

    results = []

    for repo_name in repos:
        try:
            # Search code
            code_results = g.search_code(query, repo=repo_name)
            for item in list(code_results[:5]):
                results.append(f"[code] {repo_name}/{item.path}")

            # Search issues
            issue_results = g.search_issues(query, repo=repo_name)
            for item in list(issue_results[:5]):
                state = item.state
                results.append(f"[issue #{item.number} {state}] {repo_name}: {item.title}")

        except GithubException as e:
            results.append(f"[error] {repo_name}: {e.data.get('message', str(e))}")

    if not results:
        return f"No results found for '{query}' in {', '.join(repos)}."

    return "\n".join(results[:20])


@tool
def read_github_file(repo: str, path: str) -> str:
    """Read a file from a GitHub repo. Use owner/repo format for the repo parameter."""
    try:
        g = _get_client()
    except ValueError as e:
        return str(e)

    try:
        repository = g.get_repo(repo)
        content = repository.get_contents(path)
        if isinstance(content, list):
            # It's a directory
            entries = [f"{'dir' if c.type == 'dir' else 'file'}: {c.path}" for c in content]
            return f"Directory listing for {repo}/{path}:\n" + "\n".join(entries)

        text = content.decoded_content.decode("utf-8")
        if len(text) > 8000:
            text = text[:8000] + f"\n\n... (truncated, {len(content.decoded_content)} bytes total)"
        return text

    except GithubException as e:
        return f"Error reading {repo}/{path}: {e.data.get('message', str(e))}"
