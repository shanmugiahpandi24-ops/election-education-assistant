"""
Election Process Education Assistant
Smart AI assistant to educate users about election processes
using Google Gemini AI and Google Services.

Author: shanmugiahpandi24
Challenge: Virtual PromptWars - Challenge 2 (Election Process Education)
"""

import os
import logging
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


# ─── Security helpers ────────────────────────────────────────────────────────

ALLOWED_TOPICS = {
    "voting": "voting rights and procedures",
    "registration": "voter registration process",
    "candidates": "understanding candidates and parties",
    "polling": "polling stations and how to vote",
    "results": "how election results are counted",
    "general": "general election process education",
}

def sanitize_input(text: str, max_len: int = 1000) -> str:
    """Validate and sanitize user input."""
    if not isinstance(text, str):
        raise ValueError("Input must be a string.")
    text = text.strip()
    if len(text) == 0:
        raise ValueError("Input cannot be empty.")
    if len(text) > max_len:
        raise ValueError(f"Input too long. Max {max_len} characters.")
    return text


def get_gemini_model():
    """Return configured Gemini model. Raises if key missing."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY not configured.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-1.5-flash")


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve main UI."""
    return render_template("index.html", topics=ALLOWED_TOPICS)


@app.route("/health")
def health():
    """Health check for Cloud Run."""
    return jsonify({"status": "healthy", "service": "election-education-assistant"}), 200


@app.route("/api/ask", methods=["POST"])
def ask():
    """
    Handle election education questions via Gemini AI.
    Body: { "question": str, "topic": str }
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Invalid JSON body."}), 400

        question = sanitize_input(data.get("question", ""))
        topic = data.get("topic", "general")

        if topic not in ALLOWED_TOPICS:
            topic = "general"

        topic_label = ALLOWED_TOPICS[topic]

        system_prompt = f"""You are an unbiased, factual Election Education Assistant.
Your role is to educate citizens about the democratic election process.
Focus area: {topic_label}

Rules:
- Be neutral and non-partisan at all times
- Provide factual, clear information only
- Encourage civic participation
- If asked about specific parties or candidates, remain strictly neutral
- Keep answers concise (max 3 paragraphs)
- End with one actionable tip for the user
"""
        model = get_gemini_model()
        response = model.generate_content(f"{system_prompt}\n\nQuestion: {question}")

        logger.info(f"Question answered | topic={topic}")
        return jsonify({
            "answer": response.text,
            "topic": topic,
            "status": "success"
        }), 200

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return jsonify({"error": str(e)}), 400
    except EnvironmentError as e:
        logger.error(f"Config error: {e}")
        return jsonify({"error": "AI service not configured."}), 503
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({"error": "Internal server error."}), 500


@app.route("/api/quiz", methods=["POST"])
def quiz():
    """
    Generate a quiz question about election process.
    Body: { "topic": str }
    """
    try:
        data = request.get_json(force=True) or {}
        topic = data.get("topic", "general")
        if topic not in ALLOWED_TOPICS:
            topic = "general"

        prompt = f"""Generate ONE multiple-choice quiz question about {ALLOWED_TOPICS[topic]}.
Return ONLY valid JSON in this exact format:
{{
  "question": "question text here",
  "options": ["A. option1", "B. option2", "C. option3", "D. option4"],
  "correct": "A",
  "explanation": "brief explanation why"
}}
No extra text, only JSON."""

        model = get_gemini_model()
        response = model.generate_content(prompt)

        import json
        raw = response.text.strip().replace("```json", "").replace("```", "")
        quiz_data = json.loads(raw)

        return jsonify({"quiz": quiz_data, "status": "success"}), 200

    except EnvironmentError as e:
        return jsonify({"error": "AI service not configured."}), 503
    except Exception as e:
        logger.error(f"Quiz error: {e}")
        return jsonify({"error": "Could not generate quiz."}), 500


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Route not found."}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed."}), 405


if __name__ == "__main__":
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=debug)
