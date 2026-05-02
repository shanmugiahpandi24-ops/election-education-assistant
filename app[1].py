"""
Election Process Education Assistant
Smart AI assistant to educate users about election processes
using Google Gemini AI, Google Translate, Google Firebase,
Google Sheets, and Google Cloud Logging.

Author: shanmugiahpandi24
Challenge: Virtual PromptWars - Challenge 2 (Election Process Education)
Google Services: Gemini AI, Cloud Translate, Firestore, Sheets API
"""

import os
import json
import time
import hashlib
import logging
from functools import lru_cache
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ─── In-memory cache for efficiency ─────────────────────────────────────────
_response_cache: dict = {}
CACHE_TTL = 300  # 5 minutes

# ─── Google Translate (optional) ────────────────────────────────────────────
def translate_text(text: str, target_lang: str) -> str:
    """Translate text using Google Cloud Translate API."""
    if target_lang == "en" or not target_lang:
        return text
    try:
        from google.cloud import translate_v2 as translate
        client = translate.Client()
        result = client.translate(text, target_language=target_lang)
        return result["translatedText"]
    except Exception as e:
        logger.warning(f"Translation skipped: {e}")
        return text

# ─── Google Firestore (optional) ────────────────────────────────────────────
def log_to_firestore(topic: str, question: str, lang: str):
    """Log interactions to Google Firebase Firestore."""
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            cred_json = os.environ.get("FIREBASE_CREDENTIALS")
            if cred_json:
                cred = credentials.Certificate(json.loads(cred_json))
            else:
                cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        db.collection("election_questions").add({
            "topic": topic,
            "lang": lang,
            "question_preview": question[:100],
            "timestamp": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        logger.warning(f"Firestore log skipped: {e}")

# ─── Google Sheets (optional) ────────────────────────────────────────────────
def log_to_sheets(question: str, topic: str, lang: str):
    """Log questions to Google Sheets via Sheets API."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        cred_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        sheet_id = os.environ.get("GOOGLE_SHEET_ID")
        if not cred_json or not sheet_id:
            return
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(json.loads(cred_json), scopes=scopes)
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(sheet_id).sheet1
        ws.append_row([time.strftime("%Y-%m-%d %H:%M:%S"), topic, lang, question[:200]])
    except Exception as e:
        logger.warning(f"Sheets log skipped: {e}")

# ─── Cache helpers ────────────────────────────────────────────────────────────
def cache_get(key: str):
    if key in _response_cache:
        value, ts = _response_cache[key]
        if time.time() - ts < CACHE_TTL:
            return value
        del _response_cache[key]
    return None

def cache_set(key: str, value):
    _response_cache[key] = (value, time.time())
    if len(_response_cache) > 500:
        oldest = sorted(_response_cache, key=lambda k: _response_cache[k][1])[:100]
        for k in oldest:
            del _response_cache[k]

# ─── Constants ───────────────────────────────────────────────────────────────
ALLOWED_TOPICS = {
    "voting": "voting rights and procedures",
    "registration": "voter registration process",
    "candidates": "understanding candidates and parties",
    "polling": "polling stations and how to vote",
    "results": "how election results are counted",
    "general": "general election process education",
}

SUPPORTED_LANGS = {
    "en": "English", "hi": "Hindi", "ta": "Tamil",
    "te": "Telugu", "kn": "Kannada", "ml": "Malayalam",
    "fr": "French", "es": "Spanish", "de": "German"
}

def sanitize_input(text: str, max_len: int = 1000) -> str:
    if not isinstance(text, str):
        raise ValueError("Input must be a string.")
    text = text.strip()
    if len(text) == 0:
        raise ValueError("Input cannot be empty.")
    if len(text) > max_len:
        raise ValueError(f"Input too long. Max {max_len} characters.")
    return text

@lru_cache(maxsize=1)
def get_gemini_model():
    """Return cached Gemini model instance."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY not configured.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-1.5-flash")

# ─── Routes ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", topics=ALLOWED_TOPICS, languages=SUPPORTED_LANGS)

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "service": "election-education-assistant",
        "google_services": ["gemini-ai", "cloud-translate", "firestore", "sheets-api"]
    }), 200

@app.route("/api/ask", methods=["POST"])
def ask():
    """
    Answer election questions using Google Gemini AI.
    Translates using Google Cloud Translate.
    Logs to Google Firestore and Google Sheets.
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Invalid JSON body."}), 400

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

        system_prompt = f"""You are an unbiased, factual Election Education Assistant.
Your role is to educate citizens about the democratic election process.
Focus area: {ALLOWED_TOPICS[topic]}

Rules:
- Be neutral and non-partisan at all times
- Provide factual, clear information only
- Encourage civic participation
- Keep answers concise (max 3 paragraphs)
- End with one actionable tip for the user
- Where appropriate, mention digital tools like Google Forms for registration,
  Google Maps for finding polling stations, and official government websites.
"""
        model = get_gemini_model()
        response = model.generate_content(f"{system_prompt}\n\nQuestion: {question_en}")
        answer_en = response.text

        answer = translate_text(answer_en, lang) if lang != "en" else answer_en

        result = {"answer": answer, "topic": topic, "lang": lang, "status": "success"}
        cache_set(cache_key, result)

        log_to_firestore(topic, question, lang)
        log_to_sheets(question, topic, lang)

        logger.info(f"Answered | topic={topic} lang={lang}")
        return jsonify(result), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except EnvironmentError as e:
        return jsonify({"error": "AI service not configured."}), 503
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"error": "Internal server error."}), 500

@app.route("/api/quiz", methods=["POST"])
def quiz():
    """Generate quiz using Gemini AI, translate with Google Translate."""
    try:
        data = request.get_json(force=True) or {}
        topic = data.get("topic", "general")
        lang = data.get("lang", "en")
        if topic not in ALLOWED_TOPICS:
            topic = "general"

        cache_key = hashlib.md5(f"quiz{topic}{lang}".encode()).hexdigest()
        cached = cache_get(cache_key)
        if cached:
            return jsonify({**cached, "cached": True}), 200

        prompt = f"""Generate ONE multiple-choice quiz question about {ALLOWED_TOPICS[topic]}.
Return ONLY valid JSON:
{{"question":"...","options":["A. ...","B. ...","C. ...","D. ..."],"correct":"A","explanation":"..."}}
No extra text."""

        model = get_gemini_model()
        raw = model.generate_content(prompt).text.strip().replace("```json","").replace("```","")
        quiz_data = json.loads(raw)

        if lang != "en":
            quiz_data["question"] = translate_text(quiz_data["question"], lang)
            quiz_data["options"] = [translate_text(o, lang) for o in quiz_data["options"]]
            quiz_data["explanation"] = translate_text(quiz_data["explanation"], lang)

        result = {"quiz": quiz_data, "status": "success"}
        cache_set(cache_key, result)
        return jsonify(result), 200

    except EnvironmentError:
        return jsonify({"error": "AI service not configured."}), 503
    except Exception as e:
        logger.error(f"Quiz error: {e}")
        return jsonify({"error": "Could not generate quiz."}), 500

@app.route("/api/translate", methods=["POST"])
def translate_endpoint():
    """Translate text via Google Cloud Translate API."""
    try:
        data = request.get_json(force=True)
        text = sanitize_input(data.get("text", ""))
        target = data.get("target", "en")
        if target not in SUPPORTED_LANGS:
            return jsonify({"error": "Unsupported language."}), 400
        translated = translate_text(text, target)
        return jsonify({"translated": translated, "target": target, "status": "success"}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "Translation failed."}), 500

@app.route("/api/languages", methods=["GET"])
def languages():
    return jsonify({"languages": SUPPORTED_LANGS, "status": "success"}), 200

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Route not found."}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed."}), 405

if __name__ == "__main__":
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=debug)
