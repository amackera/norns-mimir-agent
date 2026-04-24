import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

from github import GithubException


class TestSearchGithub:
    def test_works_without_token(self, monkeypatch):
        """Unauthenticated access is allowed for public repos."""
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "")

        mock_github = MagicMock()
        mock_github.search_code.return_value = []
        mock_github.search_issues.return_value = []

        with (
            patch("mimir_agent.tools.github.Github", return_value=mock_github) as mock_class,
            patch("mimir_agent.tools.github.db") as mock_db,
        ):
            mock_db.get_github_repos.return_value = ["nornscode/norns"]
            from mimir_agent.tools.github import search_github
            result = search_github.handler("test query")

        # Github was instantiated without a token argument
        mock_class.assert_called_with()
        assert "not configured" not in result

    def test_no_repos(self, monkeypatch):
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "fake-token")
        with (
            patch("mimir_agent.tools.github.Github"),
            patch("mimir_agent.tools.github.db") as mock_db,
        ):
            mock_db.get_github_repos.return_value = []
            from mimir_agent.tools.github import search_github
            result = search_github.handler("test", repo="")
            assert "No GitHub repos connected" in result

    def test_search_returns_results(self, monkeypatch):
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "fake-token")

        mock_code_item = MagicMock()
        mock_code_item.path = "src/main.py"

        mock_issue = MagicMock()
        mock_issue.number = 42
        mock_issue.state = "open"
        mock_issue.title = "Bug report"

        mock_github = MagicMock()
        mock_github.search_code.return_value = [mock_code_item]
        mock_github.search_issues.return_value = [mock_issue]

        with (
            patch("mimir_agent.tools.github.Github", return_value=mock_github),
            patch("mimir_agent.tools.github.db") as mock_db,
        ):
            mock_db.get_github_repos.return_value = ["owner/repo"]
            from mimir_agent.tools.github import search_github
            result = search_github.handler("test query")

        assert "src/main.py" in result
        assert "#42" in result
        assert "Bug report" in result

    def test_handles_github_exception(self, monkeypatch):
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "fake-token")

        mock_github = MagicMock()
        mock_github.search_code.side_effect = GithubException(403, {"message": "rate limited"}, {})

        with (
            patch("mimir_agent.tools.github.Github", return_value=mock_github),
            patch("mimir_agent.tools.github.db") as mock_db,
        ):
            mock_db.get_github_repos.return_value = ["owner/repo"]
            from mimir_agent.tools.github import search_github
            result = search_github.handler("test query")

        assert "error" in result.lower()

    def test_handles_index_error(self, monkeypatch):
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "fake-token")

        mock_github = MagicMock()
        mock_github.search_code.side_effect = IndexError("list index out of range")

        with (
            patch("mimir_agent.tools.github.Github", return_value=mock_github),
            patch("mimir_agent.tools.github.db") as mock_db,
        ):
            mock_db.get_github_repos.return_value = ["owner/repo"]
            from mimir_agent.tools.github import search_github
            result = search_github.handler("test query")

        assert "error" in result.lower()


class TestReadGithubFile:
    def test_reads_file(self, monkeypatch):
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "fake-token")

        mock_content = MagicMock()
        mock_content.decoded_content = b"file contents here"
        type(mock_content).type = PropertyMock(return_value="file")

        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = mock_content

        mock_github = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        with patch("mimir_agent.tools.github.Github", return_value=mock_github):
            from mimir_agent.tools.github import read_github_file
            result = read_github_file.handler("owner/repo", "README.md")

        assert "file contents here" in result

    def test_lists_directory(self, monkeypatch):
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "fake-token")

        entry1 = MagicMock()
        entry1.type = "file"
        entry1.path = "src/main.py"
        entry2 = MagicMock()
        entry2.type = "dir"
        entry2.path = "src/utils"

        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = [entry1, entry2]

        mock_github = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        with patch("mimir_agent.tools.github.Github", return_value=mock_github):
            from mimir_agent.tools.github import read_github_file
            result = read_github_file.handler("owner/repo", "src")

        assert "src/main.py" in result
        assert "src/utils" in result
        assert "dir:" in result

    def test_truncates_large_files(self, monkeypatch):
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "fake-token")

        mock_content = MagicMock()
        mock_content.decoded_content = b"x" * 10000

        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = mock_content

        mock_github = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        with patch("mimir_agent.tools.github.Github", return_value=mock_github):
            from mimir_agent.tools.github import read_github_file
            result = read_github_file.handler("owner/repo", "big.txt")

        assert "truncated" in result


class TestListGithubCommits:
    def test_lists_commits(self, monkeypatch):
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "fake-token")

        mock_commit = MagicMock()
        mock_commit.sha = "abc1234567890"
        mock_commit.commit.author.date = datetime(2026, 4, 15, tzinfo=timezone.utc)
        mock_commit.commit.author.name = "Dev"
        mock_commit.commit.message = "Fix bug\n\nDetails here"

        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = [mock_commit]

        mock_github = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        with patch("mimir_agent.tools.github.Github", return_value=mock_github):
            from mimir_agent.tools.github import list_github_commits
            result = list_github_commits.handler("owner/repo")

        assert "abc1234" in result
        assert "Fix bug" in result
        assert "Dev" in result

    def test_invalid_date(self, monkeypatch):
        monkeypatch.setattr("mimir_agent.config.GITHUB_TOKEN", "fake-token")

        mock_repo = MagicMock()
        mock_github = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        with patch("mimir_agent.tools.github.Github", return_value=mock_github):
            from mimir_agent.tools.github import list_github_commits
            result = list_github_commits.handler("owner/repo", since="not-a-date")

        assert "Invalid date" in result
