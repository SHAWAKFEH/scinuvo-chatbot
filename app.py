"""
app.py — The Scinuvo chatbot backend API.

This wraps the RAG logic (retrieve -> ground -> answer) into a web server the
website widget can call. It includes every safety and cost control we agreed on:

  - Model: Claude Haiku (cheapest)
  - Grounding: answers ONLY from the knowledge base
  - Medical guardrail: refuses medical/diagnosis/treatment questions
  - Bilingual: replies in the customer's language
  - Rate limiting: per-visitor caps (stops one person spamming)
  - Daily global cap: stops total spend running away
  - Short token limit: keeps each answer cheap

Endpoints:
  POST /chat   -> { "message": "..." }  returns { "reply": "..." }
  GET  /health -> simple status check

Setup:
    pip install flask flask-cors chromadb sentence-transformers anthropic
    (ANTHROPIC_API_KEY must be set in the environment)

Run locally:
    python app.py
Then the API is at http://localhost:5000
"""

import os
import time
import threading
from datetime import date

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import chromadb
from sentence_transformers import SentenceTransformer
from anthropic import Anthropic

# ----------------------------------------------------------------------
# Configuration — all the knobs in one place
# ----------------------------------------------------------------------
MODEL_EMBED = "paraphrase-multilingual-MiniLM-L12-v2"
MODEL_LLM = "claude-haiku-4-5-20251001"     # cheapest model
TOP_K = 6                                    # chunks retrieved per question
MAX_TOKENS = 700                             # cap answer length (raised so Arabic answers finish)
MAX_HISTORY = 10                             # how many prior messages to remember per chat

DAILY_GLOBAL_CAP = 2000        # max total questions answered per day (all users)
PER_IP_PER_MINUTE = 6          # max questions one visitor can send per minute
PER_IP_PER_DAY = 40            # max questions one visitor can send per day

# Which website(s) may call this API. In production, set this to your real
# domain so random sites can't use (and bill) your bot.
ALLOWED_ORIGINS = ["https://scinuvo.com", "http://localhost:5000"]

# ----------------------------------------------------------------------
# Load models and database once at startup
# ----------------------------------------------------------------------
print("Loading embedding model...")
embedder = SentenceTransformer(MODEL_EMBED)

print("Connecting to vector database...")
db = chromadb.PersistentClient(path="scinuvo_db")
collection = db.get_collection("scinuvo")

client = Anthropic()   # reads ANTHROPIC_API_KEY from environment

# Load the full catalog text once, so "show all products" always returns everything
# (retrieval alone can miss items; this guarantees the complete list).
_FULL_CATALOG = ""
try:
    import json as _json
    with open("scinuvo_knowledge.jsonl", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line:
                continue
            _r = _json.loads(_line)
            if _r.get("id") == "catalog":
                _FULL_CATALOG = f"[All Products (full list)]\n{_r.get('text_ar','')}\n{_r.get('text_en','')}"
                break
except Exception as _e:
    print(f"(catalog preload skipped: {_e})")

# Phrases that mean "show me everything" (Arabic + dialect + English)
_SHOW_ALL_HINTS = [
    "كل المنتجات", "جميع المنتجات", "كل السيرومات", "جميع السيرومات",
    "شو عندكم", "شو المنتجات", "فرجيني", "اعرضلي", "القائمة الكاملة", "وريني",
    "all products", "all serums", "full range", "everything", "product list",
    "show me all", "list all", "what products",
]

def wants_all_products(text):
    t = text.lower()
    return any(h in t for h in _SHOW_ALL_HINTS)

app = Flask(__name__)
CORS(app, origins=ALLOWED_ORIGINS)

# ----------------------------------------------------------------------
# Simple in-memory counters for rate limiting and the daily cap.
# (For a single server this is fine. If the IT team runs multiple servers,
#  they'd move these counters to a shared store like Redis — noted in README.)
# ----------------------------------------------------------------------
_lock = threading.Lock()
_state = {
    "day": date.today(),
    "global_count": 0,
    "ip_minute": {},   # ip -> [timestamps in the last minute]
    "ip_day": {},      # ip -> count today
}


def _reset_if_new_day():
    today = date.today()
    if _state["day"] != today:
        _state["day"] = today
        _state["global_count"] = 0
        _state["ip_day"] = {}
        _state["ip_minute"] = {}


def check_limits(ip):
    """Return None if allowed, or an error string if a limit is hit."""
    with _lock:
        _reset_if_new_day()

        # Daily global cap (total across everyone)
        if _state["global_count"] >= DAILY_GLOBAL_CAP:
            return "daily_global"

        # Per-IP per-day
        if _state["ip_day"].get(ip, 0) >= PER_IP_PER_DAY:
            return "ip_day"

        # Per-IP per-minute
        now = time.time()
        recent = [t for t in _state["ip_minute"].get(ip, []) if now - t < 60]
        if len(recent) >= PER_IP_PER_MINUTE:
            return "ip_minute"

        # Passed all checks -> record this request
        recent.append(now)
        _state["ip_minute"][ip] = recent
        _state["ip_day"][ip] = _state["ip_day"].get(ip, 0) + 1
        _state["global_count"] += 1
        return None


# ----------------------------------------------------------------------
# RAG logic (same as the terminal version)
# ----------------------------------------------------------------------
def is_arabic(text):
    return any("\u0600" <= ch <= "\u06FF" for ch in text)


def retrieve(question):
    q_vec = embedder.encode([question], normalize_embeddings=True).tolist()
    res = collection.query(query_embeddings=q_vec, n_results=TOP_K)
    return list(zip(res["documents"][0], res["metadatas"][0]))


SYSTEM_PROMPT = """You are the customer assistant for Scinuvo, a Jordanian company that sells the Pure Solutions skincare serums.

STRICT RULES:
1. Answer ONLY using the product information under "CONTEXT". Do not use outside knowledge; do not invent facts, prices, or claims.
2. If the answer is not in the CONTEXT, say you don't have that detail and suggest contacting info@scinuvo.com. Do this in the customer's language.
3. Reply in the SAME language the customer used. If the customer writes in Arabic, reply in clear, professional Modern Standard Arabic (الفصحى) — do NOT use slang or heavy dialect, even if the question was in dialect. If the customer writes in English, reply in English.
4. When the customer asks about a price, ALWAYS state the exact price from the CONTEXT (the price appears clearly as "PRICE:" / "السعر:"). Never say you don't have pricing if a price is present in the CONTEXT.
5. You are NOT a doctor or pharmacist. If the customer asks for medical advice, a diagnosis, treatment, whether a product is safe for a medical condition or pregnancy, drug interactions, or anything health-related beyond what is plainly in the CONTEXT, DO NOT answer it. Kindly say you can only share product information and recommend they consult a doctor or pharmacist, or contact info@scinuvo.com. Reply in the customer's language.
6. Keep answers short, warm, and professional.
7. Prices are in Jordanian Dinar (JOD / دينار أردني).
8. If you give the phone number, always write it exactly as: +962 79 0606 220 (keep it on one line, do not reformat or split the digits).
9. If the customer asks to see all products, the full range, or the catalog, list ALL SIX serums with their names and prices from the "All Products (full list)" entry in the CONTEXT. Do not stop after two or three."""


def generate_answer(question, history=None):
    # Retrieval is based on the latest question.
    retrieved = retrieve(question)
    context = "\n\n".join(f"[{m['title']}]\n{d}" for d, m in retrieved)

    # If the customer wants to see everything, guarantee the full catalog is
    # present in the context (don't rely on retrieval ranking for this).
    if wants_all_products(question) and _FULL_CATALOG:
        context = _FULL_CATALOG + "\n\n" + context

    lang = "Arabic" if is_arabic(question) else "English"

    # Build the message list: prior turns for memory, then the current question
    # (with the retrieved context attached to the current question).
    messages = []
    if history:
        # history is a list of {"role": "user"|"assistant", "content": "..."}
        for turn in history[-MAX_HISTORY:]:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content[:1500]})

    current = (
        f"CONTEXT (Scinuvo product information):\n{context}\n\n"
        f"CUSTOMER QUESTION (reply in {lang}): {question}"
    )
    messages.append({"role": "user", "content": current})

    resp = client.messages.create(
        model=MODEL_LLM,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return resp.content[0].text


# Friendly "limit reached" messages, bilingual
LIMIT_MSG = {
    "daily_global": {
        "en": "Our assistant is taking a short break for today. Please email info@scinuvo.com and we'll be glad to help!",
        "ar": "مساعدنا أخذ استراحة قصيرة لليوم. راسلنا على info@scinuvo.com وبنكون سعداء نساعدك!",
    },
    "ip_day": {
        "en": "You've reached today's message limit. Please email info@scinuvo.com for more help.",
        "ar": "وصلت للحد اليومي للرسائل. راسلنا على info@scinuvo.com لمزيد من المساعدة.",
    },
    "ip_minute": {
        "en": "You're sending messages a bit fast — please wait a moment and try again.",
        "ar": "بترسل رسائل بسرعة شوي — انتظر لحظة وحاول مرة ثانية.",
    },
}


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []   # list of prior {role, content} turns
    if not message:
        return jsonify({"reply": "Please type a question."}), 400
    if len(message) > 500:
        message = message[:500]   # cap input length (cost + abuse control)

    # Identify the visitor by IP for rate limiting.
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()

    limit_hit = check_limits(ip)
    if limit_hit:
        lang = "ar" if is_arabic(message) else "en"
        return jsonify({"reply": LIMIT_MSG[limit_hit][lang]}), 429

    try:
        reply = generate_answer(message, history=history)
    except Exception as e:
        print(f"Error generating answer: {e}")
        lang = "ar" if is_arabic(message) else "en"
        fallback = {
            "en": "Sorry, something went wrong. Please try again or email info@scinuvo.com.",
            "ar": "عذراً، صار خطأ. حاول مرة ثانية أو راسلنا على info@scinuvo.com.",
        }
        return jsonify({"reply": fallback[lang]}), 500

    return jsonify({"reply": reply})


@app.route("/", methods=["GET"])
def widget():
    # Serves the chat widget for local testing (same-origin, no CORS issues).
    # In production the widget is embedded on the website instead.
    return send_file("widget.html")


@app.route("/health", methods=["GET"])
def health():
    with _lock:
        _reset_if_new_day()
        used = _state["global_count"]
    return jsonify({"status": "ok", "questions_today": used, "daily_cap": DAILY_GLOBAL_CAP})


if __name__ == "__main__":
    # For local testing only. In production the IT team runs this behind a
    # proper server (gunicorn/waitress) with HTTPS — see the README.
    app.run(host="0.0.0.0", port=5000, debug=False)
