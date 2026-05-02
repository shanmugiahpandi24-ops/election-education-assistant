# VoteWise — Election Process Education Assistant

A smart, AI-powered assistant to educate citizens about the democratic election process. Built with Google Gemini AI for Virtual PromptWars Challenge 2.

## Features
- 🗳️ Ask questions about voting, registration, polling, candidates, and results
- 🎯 Interactive quiz to test election knowledge
- 🔒 Secure — no hardcoded API keys, rate-aware, input validated
- ♿ Fully accessible (ARIA labels, keyboard navigation, skip links)
- ☁️ Deployable on Google Cloud Run

## Tech Stack
- **Backend**: Python / Flask
- **AI**: Google Gemini 1.5 Flash
- **Frontend**: HTML5, CSS3, Vanilla JS
- **Deployment**: Docker + Google Cloud Run

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/election-education-assistant
cd election-education-assistant

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY

# 4. Run locally
python app.py
```

## Run Tests

```bash
pytest tests/ -v
```

## Deploy to Google Cloud Run

```bash
gcloud run deploy election-assistant \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_API_KEY=your_key_here
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main UI |
| GET | `/health` | Health check |
| POST | `/api/ask` | Ask election question |
| POST | `/api/quiz` | Get quiz question |

## Challenge Criteria Coverage

| Criteria | Implementation |
|----------|---------------|
| Code Quality | Clean modules, docstrings, logging |
| Security | No hardcoded keys, input validation, env vars |
| Efficiency | Lightweight Flask, minimal dependencies |
| Testing | pytest with mocks, 15+ test cases |
| Accessibility | ARIA labels, skip links, keyboard nav, semantic HTML |
| Google Services | Google Gemini AI (generative AI) |
