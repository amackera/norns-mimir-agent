from unittest.mock import patch, MagicMock

from mimir_agent.eval import classify_thread, should_solicit_feedback, build_feedback_dm


class TestClassifyThread:
    def test_returns_parsed_classification(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text='{"outcome": "explicit_success", "evidence": "user said thanks", "confidence": 0.9}')]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp

        with patch("mimir_agent.eval.anthropic.Anthropic", return_value=mock_client):
            result = classify_thread("what is norns?", "A durable runtime.", ["thanks!"])

        assert result["outcome"] == "explicit_success"
        assert result["confidence"] == 0.9

    def test_handles_unparseable_response(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="not json")]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp

        with patch("mimir_agent.eval.anthropic.Anthropic", return_value=mock_client):
            result = classify_thread("q", "a", [])

        assert result["outcome"] == "ambiguous"
        assert result["confidence"] == 0.0

    def test_implicit_success_no_followups(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text='{"outcome": "implicit_success", "evidence": "no follow-up", "confidence": 0.7}')]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp

        with patch("mimir_agent.eval.anthropic.Anthropic", return_value=mock_client):
            result = classify_thread("q", "a", [])

        assert result["outcome"] == "implicit_success"
        # Verify the prompt mentions no follow-ups
        call_kwargs = mock_client.messages.create.call_args[1]
        user_msg = call_kwargs["messages"][0]["content"]
        assert "No follow-up messages" in user_msg


class TestShouldSolicitFeedback:
    def test_returns_bool(self):
        result = should_solicit_feedback()
        assert isinstance(result, bool)

    def test_sampling_rate(self):
        # Over 10000 trials, should be close to 5%
        results = [should_solicit_feedback() for _ in range(10000)]
        rate = sum(results) / len(results)
        assert 0.02 < rate < 0.10  # loose bounds


class TestBuildFeedbackDm:
    def test_includes_question_and_answer(self):
        dm = build_feedback_dm("what is norns?", "A durable runtime for AI agents.")
        assert "what is norns?" in dm
        assert "durable runtime" in dm
        assert "yes / no / partially" in dm

    def test_truncates_long_text(self):
        long_q = "x" * 200
        dm = build_feedback_dm(long_q, "short answer")
        assert "..." in dm
        assert len(dm) < 500
