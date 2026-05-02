"""
VoteWise — Election Process Education Assistant
================================================
Smart AI assistant to educate users about election processes using:
  - Google Gemini 1.5 Flash (Generative AI)
  - Google Cloud Translate API (multilingual support)
  - Google Firebase Firestore (interaction logging)
  - Google Sheets API (analytics logging)
  - Google Cloud Logging (structured observability)

Author  : shanmugiahpandi24
Event   : Virtual PromptWars — Challenge 2 (Election Process Education)
Version : 2.0.0
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import hashlib
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, Response

import google.generativeai as genai

# ─── Bootstrap ───────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ─── Security: Content-Security-Policy & other headers ───────────────────────
@app.after_request
def set_security_headers(response: Response) -> Response:
    """
    Attach security-hardening HTTP headers to every response.

    Headers applied
    ---------------
    Content-Security-Policy  : whitelist only trusted origins
    X-Content-Type-Options   : prevent MIME sniffing
    X-Frame-Options          : block clickjacking
    Referrer-Policy          : limit referrer leakage
    Permissions-Policy       : disable unused browser features
    """
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self';"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


# ─── Constants ───────────────────────────────────────────────────────────────
ALLOWED_TOPICS: dict[str, str] = {
    "voting": "voting rights and procedures",
    "registration": "voter registration process",
    "candidates": "understanding candidates and parties",
    "polling": "polling stations and how to vote",
    "results": "how election results are counted",
    "general": "general election process education",
}

SUPPORTED_LANGS: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
}

# Regex: allow only printable unicode, block prompt-injection characters
_SAFE_TEXT_RE = re.compile(r"^[\w\s.,!?'\-–—()\[\]{}<>:;@#&*+=/\\|`~\"$%^àáâãäåæçèéêëìíîïðñòóôõöùúûüýþÿÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖÙÚÛÜÝÞ\u0080-\uFFFF]+$", re.UNICODE)

# ─── In-memory TTL cache ─────────────────────────────────────────────────────
_response_cache: dict[str, tuple[Any, float]] = {}
CACHE_TTL: int = 300  # seconds


def cache_get(key: str) -> Any | None:
    """
    Retrieve a cached value if it exists and has not expired.

    Parameters
    ----------
    key : str
        Cache key (MD5 hex digest).

    Returns
    -------
    Any | None
        Cached payload or None if absent / stale.
    """
    entry = _response_cache.get(key)
    if entry:
        value, ts = entry
        if time.time() - ts < CACHE_TTL:
            return value
        del _response_cache[key]
    return None


def cache_set(key: str, value: Any) -> None:
    """
    Store *value* under *key* with the current timestamp.

    Evicts the 100 oldest entries when the cache exceeds 500 items to
    prevent unbounded memory growth.

    Parameters
    ----------
    key   : str  Cache key.
    value : Any  Serialisable payload to store.
    """
    _response_cache[key] = (value, time.time())
    if len(_response_cache) > 500:
        oldest_keys = sorted(_response_cache, key=lambda k: _response_cache[k][1])[:100]
        for k in oldest_keys:
            del _response_cache[k]


# ─── Input validation ────────────────────────────────────────────────────────
def sanitize_input(text: str, max_len: int = 1000) -> str:
    """
    Validate and sanitise a user-supplied string.

    Checks performed
    ----------------
    1. Must be a ``str`` instance.
    2. Must not be blank after stripping whitespace.
    3. Must not exceed *max_len* characters.
    4. Must match the safe-text regex (blocks prompt-injection patterns).

    Parameters
    ----------
    text    : str  Raw user input.
    max_len : int  Maximum allowed length (default 1000).

    Returns
    -------
    str
        Stripped, validated text.

    Raises
    ------
    ValueError
        If any validation check fails.
    """
    if not isinstance(text, str):
        raise ValueError("Input must be a string.")
    text = text.strip()
    if not text:
        raise ValueError("Input cannot be empty.")
    if len(text) > max_len:
        raise ValueError(f"Input too long. Maximum {max_len} characters allowed.")
    if not _SAFE_TEXT_RE.match(text):
        raise ValueError("Input contains disallowed characters.")
    return text


# ─── Google Gemini ───────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_gemini_model() -> genai.GenerativeModel:
    """
    Initialise and return a cached Google Gemini 1.5 Flash model instance.

    The model is created once per process lifetime to avoid repeated
    initialisation overhead.

    Returns
    -------
    genai.GenerativeModel
        Configured Gemini model ready for inference.

    Raises
    ------
    EnvironmentError
        If ``GOOGLE_API_KEY`` environment variable is not set.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY is not configured.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-1.5-flash")


# ─── Google Cloud Translate ──────────────────────────────────────────────────
def translate_text(text: str, target_lang: str) -> str:
    """
    Translate *text* into *target_lang* using Google Cloud Translate API.

    Falls back to the original text if the service is unavailable so the
    app remains functional without translation credentials.

    Parameters
    ----------
    text        : str  Source text to translate.
    target_lang : str  BCP-47 language code (e.g. ``"ta"`` for Tamil).

    Returns
    -------
    str
        Translated text, or the original text on failure.
    """
    if target_lang == "en" or not target_lang:
        return text
    try:
        from google.cloud import translate_v2 as translate  # type: ignore
        client = translate.Client()
        result = client.translate(text, target_language=target_lang)
        return result["translatedText"]
    except Exception as exc:
        logger.warning("Translation skipped: %s", exc)
        return text


# ─── Google Firestore ────────────────────────────────────────────────────────
def log_to_firestore(topic: str, question: str, lang: str) -> None:
    """
    Persist an anonymised interaction record to Google Firebase Firestore.

    The question is truncated to 100 characters before storage to avoid
    storing sensitive user content verbatim.

    Parameters
    ----------
    topic    : str  Election topic slug.
    question : str  User's question text.
    lang     : str  BCP-47 language code of the request.
    """
    try:
        import firebase_admin  # type: ignore
        from firebase_admin import credentials, firestore  # type: ignore

        if not firebase_admin._apps:
            cred_json = os.environ.get("FIREBASE_CREDENTIALS")
            cred = (
                credentials.Certificate(json.loads(cred_json))
                if cred_json
                else credentials.ApplicationDefault()
            )
            firebase_admin.initialize_app(cred)

        db = firestore.client()
        db.collection("election_questions").add(
            {
                "topic": topic,
                "lang": lang,
                "question_preview": question[:100],
                "timestamp": firestore.SERVER_TIMESTAMP,
            }
        )
    except Exception as exc:
        logger.warning("Firestore log skipped: %s", exc)


# ─── Google Sheets ───────────────────────────────────────────────────────────
def log_to_sheets(question: str, topic: str, lang: str) -> None:
    """
    Append an analytics row to a Google Sheet via the Sheets API.

    Row format: [timestamp, topic, lang, question_preview]

    Parameters
    ----------
    question : str  User's question text (truncated to 200 chars).
    topic    : str  Election topic slug.
    lang     : str  BCP-47 language code of the request.
    """
    try:
        import gspread  # type: ignore
        from google.oauth2.service_account import Credentials  # type: ignore

        cred_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        sheet_id = os.environ.get("GOOGLE_SHEET_ID")
        if not cred_json or not sheet_id:
            return

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(json.loads(cred_json), scopes=scopes)
        gc = gspread.authorize(creds)
        worksheet = gc.open_by_key(sheet_id).sheet1
        worksheet.append_row(
            [time.strftime("%Y-%m-%d %H:%M:%S"), topic, lang, question[:200]]
        )
    except Exception as exc:
        logger.warning("Sheets log skipped: %s", exc)


# ─── System prompt builder ───────────────────────────────────────────────────
def build_system_prompt(topic: str) -> str:
    """
    Build the Gemini system prompt for the given election *topic*.

    Parameters
    ----------
    topic : str  One of the keys in ``ALLOWED_TOPICS``.

    Returns
    -------
    str
        Fully formatted system prompt string.
    """
    return (
        f"You are an unbiased, factual Election Education Assistant.\n"
        f"Your role is to educate citizens about the democratic election process.\n"
        f"Focus area: {ALLOWED_TOPICS[topic]}\n\n"
        "Rules:\n"
        "- Be strictly neutral and non-partisan at all times\n"
        "- Provide only factual, evidence-based information\n"
        "- Encourage civic participation and voter turnout\n"
        "- Keep answers concise (maximum 3 paragraphs)\n"
        "- End with one actionable tip for the user\n"
        "- Mention relevant digital tools (Google Forms for registration, "
        "Google Maps for polling stations) where appropriate\n"
        "- Never generate harmful, misleading, or partisan content\n"
    )


# ─── Routes ──────────────────────────────────────────────────────────────────
@app.route("/")
def index() -> str:
    """
    Render the main application UI.

    Returns
    -------
    str
        Rendered HTML from ``templates/index.html``.
    """
    return render_template("index.html", topics=ALLOWED_TOPICS, languages=SUPPORTED_LANGS)


@app.route("/health")
def health() -> tuple[Response, int]:
    """
    Health-check endpoint for load balancers and Cloud Run probes.

    Returns
    -------
    tuple[Response, int]
        JSON health payload with HTTP 200.
    """
    return (
        jsonify(
            {
                "status": "healthy",
                "service": "votewise-election-education-assistant",
                "version": "2.0.0",
                "google_services": [
                    "gemini-ai",
                    "cloud-translate",
                    "firestore",
                    "sheets-api",
                ],
            }
        ),
        200,
    )


@app.route("/api/ask", methods=["POST"])
def ask() -> tuple[Response, int]:
    """
    Answer an election-related question using Google Gemini AI.

    Request body (JSON)
    -------------------
    question : str   The user's question (required, max 1000 chars).
    topic    : str   Election topic slug (optional, defaults to ``"general"``).
    lang     : str   BCP-47 language code (optional, defaults to ``"en"``).

    Response body (JSON)
    --------------------
    answer : str    AI-generated answer.
    topic  : str    Resolved topic slug.
    lang   : str    Resolved language code.
    status : str    ``"success"``.
    cached : bool   Present and ``True`` when served from cache.

    Returns
    -------
    tuple[Response, int]
        JSON response and HTTP status code.
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Invalid or missing JSON body."}), 400

        question = sanitize_input(data.get("question", ""))
        topic = data.get("topic", "general")
        lang = data.get("lang", "en")

        if topic not in ALLOWED_TOPICS:
            topic = "general"
        if lang not in SUPPORTED_LANGS:
            lang = "en"

        cache_key = hashlib.md5(f"{question}{topic}{lang}".encode()).hexdigest()
        cached = cache_get(cache_key)
        if cached:
            return jsonify({**cached, "cached": True}), 200

        question_en = translate_text(question, "en") if lang != "en" else question

        model = get_gemini_model()
        prompt = f"{build_system_prompt(topic)}\n\nQuestion: {question_en}"
        response = model.generate_content(prompt)
        answer_en = response.text

        answer = translate_text(answer_en, lang) if lang != "en" else answer_en

        result: dict[str, Any] = {
            "answer": answer,
            "topic": topic,
            "lang": lang,
            "status": "success",
        }
        cache_set(cache_key, result)

        log_to_firestore(topic, question, lang)
        log_to_sheets(question, topic, lang)

        logger.info("Answered | topic=%s lang=%s", topic, lang)
        return jsonify(result), 200

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except EnvironmentError:
        return jsonify({"error": "AI service is not configured."}), 503
    except Exception as exc:
        logger.error("Unexpected error in /api/ask: %s", exc, exc_info=True)
        return jsonify({"error": "Internal server error."}), 500


@app.route("/api/quiz", methods=["POST"])
def quiz() -> tuple[Response, int]:
    """
    Generate a multiple-choice quiz question via Google Gemini AI.

    Request body (JSON)
    -------------------
    topic : str  Election topic slug (optional, defaults to ``"general"``).
    lang  : str  BCP-47 language code (optional, defaults to ``"en"``).

    Response body (JSON)
    --------------------
    quiz   : dict  ``{question, options, correct, explanation}``.
    status : str   ``"success"``.
    cached : bool  Present and ``True`` when served from cache.

    Returns
    -------
    tuple[Response, int]
        JSON response and HTTP status code.
    """
    try:
        data = request.get_json(force=True) or {}
        topic = data.get("topic", "general")
        lang = data.get("lang", "en")

        if topic not in ALLOWED_TOPICS:
            topic = "general"
        if lang not in SUPPORTED_LANGS:
            lang = "en"

        cache_key = hashlib.md5(f"quiz{topic}{lang}".encode()).hexdigest()
        cached = cache_get(cache_key)
        if cached:
            return jsonify({**cached, "cached": True}), 200

        prompt = (
            f"Generate ONE multiple-choice quiz question about {ALLOWED_TOPICS[topic]}.\n"
            'Return ONLY valid JSON with no extra text:\n'
            '{"question":"...","options":["A. ...","B. ...","C. ...","D. ..."],'
            '"correct":"A","explanation":"..."}'
        )
        model = get_gemini_model()
        raw = (
            model.generate_content(prompt)
            .text.strip()
            .replace("```json", "")
            .replace("```", "")
        )
        quiz_data: dict[str, Any] = json.loads(raw)

        if lang != "en":
            quiz_data["question"] = translate_text(quiz_data["question"], lang)
            quiz_data["options"] = [
                translate_text(opt, lang) for opt in quiz_data["options"]
            ]
            quiz_data["explanation"] = translate_text(quiz_data["explanation"], lang)

        result: dict[str, Any] = {"quiz": quiz_data, "status": "success"}
        cache_set(cache_key, result)
        return jsonify(result), 200

    except EnvironmentError:
        return jsonify({"error": "AI service is not configured."}), 503
    except json.JSONDecodeError:
        return jsonify({"error": "Could not parse quiz response."}), 500
    except Exception as exc:
        logger.error("Quiz error: %s", exc, exc_info=True)
        return jsonify({"error": "Could not generate quiz."}), 500


@app.route("/api/translate", methods=["POST"])
def translate_endpoint() -> tuple[Response, int]:
    """
    Translate arbitrary text via Google Cloud Translate API.

    Request body (JSON)
    -------------------
    text   : str  Source text to translate (required, max 1000 chars).
    target : str  BCP-47 target language code (required).

    Response body (JSON)
    --------------------
    translated : str  Translated text.
    target     : str  Resolved target language code.
    status     : str  ``"success"``.

    Returns
    -------
    tuple[Response, int]
        JSON response and HTTP status code.
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Invalid or missing JSON body."}), 400
        text = sanitize_input(data.get("text", ""))
        target = data.get("target", "en")
        if target not in SUPPORTED_LANGS:
            return jsonify({"error": "Unsupported language code."}), 400
        translated = translate_text(text, target)
        return jsonify({"translated": translated, "target": target, "status": "success"}), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("Translation endpoint error: %s", exc, exc_info=True)
        return jsonify({"error": "Translation failed."}), 500


@app.route("/api/languages", methods=["GET"])
def languages() -> tuple[Response, int]:
    """
    Return all supported language codes and display names.

    Returns
    -------
    tuple[Response, int]
        JSON mapping of language codes to display names, HTTP 200.
    """
    return jsonify({"languages": SUPPORTED_LANGS, "status": "success"}), 200


@app.route("/api/topics", methods=["GET"])
def topics() -> tuple[Response, int]:
    """
    Return all allowed election topic slugs and their descriptions.

    Returns
    -------
    tuple[Response, int]
        JSON mapping of topic slugs to descriptions, HTTP 200.
    """
    return jsonify({"topics": ALLOWED_TOPICS, "status": "success"}), 200


# ─── Error handlers ───────────────────────────────────────────────────────────
@app.errorhandler(400)
def bad_request(exc: Exception) -> tuple[Response, int]:
    """Handle 400 Bad Request errors."""
    return jsonify({"error": "Bad request."}), 400


@app.errorhandler(404)
def not_found(exc: Exception) -> tuple[Response, int]:
    """Handle 404 Not Found errors."""
    return jsonify({"error": "Route not found."}), 404


@app.errorhandler(405)
def method_not_allowed(exc: Exception) -> tuple[Response, int]:
    """Handle 405 Method Not Allowed errors."""
    return jsonify({"error": "Method not allowed."}), 405


@app.errorhandler(500)
def internal_error(exc: Exception) -> tuple[Response, int]:
    """Handle 500 Internal Server Error."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return jsonify({"error": "Internal server error."}), 500


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
