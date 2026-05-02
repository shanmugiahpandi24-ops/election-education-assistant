"""
Unit Tests - Election Education Assistant
Covers: input validation, API endpoints, error handling
"""

import pytest
import json
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, sanitize_input

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

# ── sanitize_input ──────────────────────────────────────────────────────────

class TestSanitizeInput:
    def test_valid_string(self):
        assert sanitize_input("How do I vote?") == "How do I vote?"

    def test_strips_whitespace(self):
        assert sanitize_input("  hello  ") == "hello"

    def test_rejects_non_string(self):
        with pytest.raises(ValueError):
            sanitize_input(999)

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            sanitize_input("   ")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError):
            sanitize_input("x" * 1001)

    def test_max_length_ok(self):
        result = sanitize_input("a" * 1000)
        assert len(result) == 1000

# ── Health ───────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_returns_healthy(self, client):
        data = json.loads(client.get("/health").data)
        assert data["status"] == "healthy"

    def test_returns_service_name(self, client):
        data = json.loads(client.get("/health").data)
        assert "service" in data

# ── /api/ask ─────────────────────────────────────────────────────────────────

class TestAskEndpoint:
    def test_missing_question_returns_400(self, client):
        r = client.post("/api/ask",
            data=json.dumps({"topic": "voting"}),
            content_type="application/json")
        assert r.status_code == 400

    def test_empty_question_returns_400(self, client):
        r = client.post("/api/ask",
            data=json.dumps({"question": "   "}),
            content_type="application/json")
        assert r.status_code == 400

    @patch("app.get_gemini_model")
    def test_valid_question_returns_200(self, mock_gemini, client):
        mock = MagicMock()
        mock.generate_content.return_value.text = "Here is how voting works..."
        mock_gemini.return_value = mock

        r = client.post("/api/ask",
            data=json.dumps({"question": "How do I vote?", "topic": "voting"}),
            content_type="application/json")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["status"] == "success"
        assert "answer" in data

    @patch("app.get_gemini_model")
    def test_invalid_topic_falls_back_to_general(self, mock_gemini, client):
        mock = MagicMock()
        mock.generate_content.return_value.text = "General info"
        mock_gemini.return_value = mock

        r = client.post("/api/ask",
            data=json.dumps({"question": "Tell me something", "topic": "invalid_topic"}),
            content_type="application/json")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["topic"] == "general"

    def test_no_api_key_returns_503(self, client):
        with patch("app.get_gemini_model", side_effect=EnvironmentError("No key")):
            r = client.post("/api/ask",
                data=json.dumps({"question": "How do I vote?"}),
                content_type="application/json")
            assert r.status_code == 503

# ── /api/quiz ─────────────────────────────────────────────────────────────────

class TestQuizEndpoint:
    @patch("app.get_gemini_model")
    def test_returns_quiz_json(self, mock_gemini, client):
        quiz = {
            "question": "What is a ballot?",
            "options": ["A. A vote", "B. A ticket", "C. A paper used to cast vote", "D. None"],
            "correct": "C",
            "explanation": "A ballot is the official paper for casting votes."
        }
        mock = MagicMock()
        mock.generate_content.return_value.text = json.dumps(quiz)
        mock_gemini.return_value = mock

        r = client.post("/api/quiz",
            data=json.dumps({"topic": "voting"}),
            content_type="application/json")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["status"] == "success"
        assert "quiz" in data

# ── Error handlers ────────────────────────────────────────────────────────────

class TestErrorHandlers:
    def test_404_returns_json(self, client):
        r = client.get("/nonexistent")
        assert r.status_code == 404
        data = json.loads(r.data)
        assert "error" in data
