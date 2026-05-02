"""
tests/test_app.py
=================
Comprehensive test suite for VoteWise Election Education Assistant.

Coverage targets
----------------
- Input validation / sanitization
- Cache helpers (get / set / eviction)
- All API endpoints (happy path + error paths)
- Security headers
- Error handlers (404, 405, 500)
- Edge cases: empty body, oversized input, bad JSON, unsupported lang/topic

Run with:
    pytest tests/ -v --tb=short
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

# ─── App fixture ─────────────────────────────────────────────────────────────
@pytest.fixture()
def client():
    """Create a Flask test client with testing mode enabled."""
    import app as app_module  # noqa: PLC0415

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the in-memory cache before every test for isolation."""
    import app as app_module  # noqa: PLC0415

    app_module._response_cache.clear()
    yield
    app_module._response_cache.clear()


# ─── sanitize_input ───────────────────────────────────────────────────────────
class TestSanitizeInput:
    """Unit tests for the sanitize_input helper."""

    def test_valid_string_returned_stripped(self):
        from app import sanitize_input
        assert sanitize_input("  hello world  ") == "hello world"

    def test_empty_string_raises(self):
        from app import sanitize_input
        with pytest.raises(ValueError, match="empty"):
            sanitize_input("   ")

    def test_non_string_raises(self):
        from app import sanitize_input
        with pytest.raises(ValueError, match="string"):
            sanitize_input(123)  # type: ignore[arg-type]

    def test_too_long_raises(self):
        from app import sanitize_input
        with pytest.raises(ValueError, match="long"):
            sanitize_input("a" * 1001)

    def test_custom_max_len(self):
        from app import sanitize_input
        with pytest.raises(ValueError, match="long"):
            sanitize_input("hello", max_len=3)

    def test_disallowed_characters_raise(self):
        from app import sanitize_input
        with pytest.raises(ValueError, match="disallowed"):
            sanitize_input("\x00\x01\x02")

    def test_unicode_question_accepted(self):
        from app import sanitize_input
        result = sanitize_input("வாக்களிக்கும் முறை என்ன?")
        assert len(result) > 0


# ─── Cache helpers ────────────────────────────────────────────────────────────
class TestCache:
    """Unit tests for cache_get / cache_set."""

    def test_set_and_get_returns_value(self):
        from app import cache_get, cache_set
        cache_set("k1", {"data": 42})
        assert cache_get("k1") == {"data": 42}

    def test_get_missing_key_returns_none(self):
        from app import cache_get
        assert cache_get("nonexistent") is None

    def test_expired_entry_returns_none(self):
        import app as app_module
        from app import cache_get, cache_set

        cache_set("k2", "value")
        # Manually expire the entry
        key, (val, _) = "k2", app_module._response_cache["k2"]
        app_module._response_cache["k2"] = (val, time.time() - 9999)
        assert cache_get("k2") is None

    def test_eviction_when_cache_full(self):
        import app as app_module
        from app import cache_set

        # Fill cache beyond 500 items
        for i in range(510):
            cache_set(f"key{i}", i)
        assert len(app_module._response_cache) <= 500


# ─── GET / ────────────────────────────────────────────────────────────────────
class TestIndexRoute:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_index_content_type_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.content_type


# ─── GET /health ──────────────────────────────────────────────────────────────
class TestHealthRoute:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_payload(self, client):
        data = client.get("/health").get_json()
        assert data["status"] == "healthy"
        assert "google_services" in data
        assert "gemini-ai" in data["google_services"]

    def test_health_version_present(self, client):
        data = client.get("/health").get_json()
        assert "version" in data


# ─── GET /api/languages ───────────────────────────────────────────────────────
class TestLanguagesRoute:
    def test_returns_200(self, client):
        assert client.get("/api/languages").status_code == 200

    def test_contains_english(self, client):
        data = client.get("/api/languages").get_json()
        assert "en" in data["languages"]

    def test_contains_tamil(self, client):
        data = client.get("/api/languages").get_json()
        assert "ta" in data["languages"]


# ─── GET /api/topics ─────────────────────────────────────────────────────────
class TestTopicsRoute:
    def test_returns_200(self, client):
        assert client.get("/api/topics").status_code == 200

    def test_contains_voting(self, client):
        data = client.get("/api/topics").get_json()
        assert "voting" in data["topics"]

    def test_status_success(self, client):
        data = client.get("/api/topics").get_json()
        assert data["status"] == "success"


# ─── POST /api/ask ───────────────────────────────────────────────────────────
class TestAskRoute:
    """Tests for the main /api/ask endpoint."""

    def _mock_model(self, answer_text: str = "Election info here."):
        model = MagicMock()
        model.generate_content.return_value.text = answer_text
        return model

    def test_valid_request_returns_200(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model()), \
             patch("app.log_to_firestore"), patch("app.log_to_sheets"):
            resp = client.post(
                "/api/ask",
                json={"question": "How do I register to vote?", "topic": "registration", "lang": "en"},
            )
        assert resp.status_code == 200

    def test_valid_request_returns_answer(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model("Test answer")), \
             patch("app.log_to_firestore"), patch("app.log_to_sheets"):
            data = client.post(
                "/api/ask",
                json={"question": "What is voting?"},
            ).get_json()
        assert data["answer"] == "Test answer"
        assert data["status"] == "success"

    def test_invalid_topic_defaults_to_general(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model()), \
             patch("app.log_to_firestore"), patch("app.log_to_sheets"):
            data = client.post(
                "/api/ask",
                json={"question": "What is democracy?", "topic": "INVALID_TOPIC"},
            ).get_json()
        assert data["topic"] == "general"

    def test_invalid_lang_defaults_to_en(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model()), \
             patch("app.log_to_firestore"), patch("app.log_to_sheets"):
            data = client.post(
                "/api/ask",
                json={"question": "What is democracy?", "lang": "xx"},
            ).get_json()
        assert data["lang"] == "en"

    def test_empty_question_returns_400(self, client):
        resp = client.post("/api/ask", json={"question": "   "})
        assert resp.status_code == 400

    def test_missing_question_returns_400(self, client):
        resp = client.post("/api/ask", json={})
        assert resp.status_code == 400

    def test_oversized_question_returns_400(self, client):
        resp = client.post("/api/ask", json={"question": "a" * 1001})
        assert resp.status_code == 400

    def test_no_api_key_returns_503(self, client):
        with patch("app.get_gemini_model", side_effect=EnvironmentError("no key")):
            resp = client.post("/api/ask", json={"question": "What is voting?"})
        assert resp.status_code == 503

    def test_cached_response_served(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model("Cached")), \
             patch("app.log_to_firestore"), patch("app.log_to_sheets"):
            client.post("/api/ask", json={"question": "What is voting?"})
            data = client.post("/api/ask", json={"question": "What is voting?"}).get_json()
        assert data.get("cached") is True

    def test_non_english_question_translated(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model()), \
             patch("app.translate_text", return_value="Translated") as mock_trans, \
             patch("app.log_to_firestore"), patch("app.log_to_sheets"):
            client.post("/api/ask", json={"question": "What is voting?", "lang": "ta"})
        assert mock_trans.called

    def test_invalid_json_returns_400(self, client):
        resp = client.post("/api/ask", data="not json", content_type="application/json")
        assert resp.status_code in (400, 500)

    def test_unexpected_exception_returns_500(self, client):
        with patch("app.get_gemini_model", side_effect=RuntimeError("boom")):
            resp = client.post("/api/ask", json={"question": "What is voting?"})
        assert resp.status_code == 500


# ─── POST /api/quiz ───────────────────────────────────────────────────────────
class TestQuizRoute:
    """Tests for the /api/quiz endpoint."""

    _QUIZ_JSON = json.dumps({
        "question": "What is a ballot?",
        "options": ["A. A vote", "B. A tax", "C. A law", "D. A party"],
        "correct": "A",
        "explanation": "A ballot is used to cast a vote.",
    })

    def _mock_model(self):
        model = MagicMock()
        model.generate_content.return_value.text = self._QUIZ_JSON
        return model

    def test_quiz_returns_200(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model()):
            assert client.post("/api/quiz", json={"topic": "voting"}).status_code == 200

    def test_quiz_payload_structure(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model()):
            data = client.post("/api/quiz", json={}).get_json()
        assert "quiz" in data
        assert "question" in data["quiz"]
        assert "options" in data["quiz"]
        assert "correct" in data["quiz"]
        assert "explanation" in data["quiz"]

    def test_quiz_invalid_topic_defaults(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model()):
            resp = client.post("/api/quiz", json={"topic": "BAD"})
        assert resp.status_code == 200

    def test_quiz_no_api_key_returns_503(self, client):
        with patch("app.get_gemini_model", side_effect=EnvironmentError):
            assert client.post("/api/quiz", json={}).status_code == 503

    def test_quiz_cached(self, client):
        with patch("app.get_gemini_model", return_value=self._mock_model()):
            client.post("/api/quiz", json={"topic": "voting", "lang": "en"})
            data = client.post("/api/quiz", json={"topic": "voting", "lang": "en"}).get_json()
        assert data.get("cached") is True

    def test_quiz_bad_json_from_model_returns_500(self, client):
        bad_model = MagicMock()
        bad_model.generate_content.return_value.text = "NOT JSON {{{}"
        with patch("app.get_gemini_model", return_value=bad_model):
            resp = client.post("/api/quiz", json={})
        assert resp.status_code == 500


# ─── POST /api/translate ─────────────────────────────────────────────────────
class TestTranslateRoute:
    def test_valid_translation_returns_200(self, client):
        with patch("app.translate_text", return_value="Translated text"):
            resp = client.post("/api/translate", json={"text": "Hello", "target": "ta"})
        assert resp.status_code == 200

    def test_unsupported_language_returns_400(self, client):
        resp = client.post("/api/translate", json={"text": "Hello", "target": "zz"})
        assert resp.status_code == 400

    def test_empty_text_returns_400(self, client):
        resp = client.post("/api/translate", json={"text": "   ", "target": "ta"})
        assert resp.status_code == 400

    def test_missing_body_returns_400(self, client):
        resp = client.post("/api/translate", json={})
        assert resp.status_code == 400

    def test_translated_field_in_response(self, client):
        with patch("app.translate_text", return_value="வணக்கம்"):
            data = client.post("/api/translate", json={"text": "Hello", "target": "ta"}).get_json()
        assert data["translated"] == "வணக்கம்"
        assert data["status"] == "success"


# ─── Security headers ────────────────────────────────────────────────────────
class TestSecurityHeaders:
    def test_csp_header_present(self, client):
        resp = client.get("/health")
        assert "Content-Security-Policy" in resp.headers

    def test_x_content_type_options(self, client):
        assert client.get("/health").headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        assert client.get("/health").headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, client):
        assert "Referrer-Policy" in client.get("/health").headers

    def test_permissions_policy(self, client):
        assert "Permissions-Policy" in client.get("/health").headers


# ─── Error handlers ──────────────────────────────────────────────────────────
class TestErrorHandlers:
    def test_404_returns_json(self, client):
        resp = client.get("/nonexistent-route-xyz")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "Route not found."

    def test_405_on_wrong_method(self, client):
        resp = client.get("/api/ask")
        assert resp.status_code == 405

    def test_405_response_is_json(self, client):
        resp = client.get("/api/ask")
        data = resp.get_json()
        assert "error" in data
