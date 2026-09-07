# Scinuvo Customer Chatbot

A bilingual (Arabic / English) customer-support chatbot for the Scinuvo Pure Solutions
skincare range. It answers questions about products, prices, usage, and routines,
grounded strictly in Scinuvo's own product data, and refuses medical advice.

Built with a Retrieval-Augmented Generation (RAG) pipeline: multilingual embeddings +
a vector database (ChromaDB) for retrieval, and Claude (Anthropic API) for generation.

## Demo

The assistant greets visitors, detects their language, offers quick starter questions,
and answers about the six Pure Solutions serums — in Arabic (right-to-left) or English.

![Chatbot screenshot](demo.png)

**Running the demo:** start the server (`python app.py`) and open `http://localhost:5000`.
A temporary public link can be shared via ngrok while the server is running. A permanent,
always-on deployment is handled by the hosting steps below (for the IT team).

---

## What's in this repo

| File | Purpose |
|------|---------|
| `app.py` | The backend API (Flask). Serves `/chat` and the widget. |
| `widget.html` | The chat widget shown to customers. |
| `ingest.py` | Builds the vector database from the knowledge base. |
| `scinuvo_knowledge.jsonl` | The product knowledge base (customer-safe content). |
| `scrape.py` | Pulls product data from scinuvo.com to update the knowledge base. |
| `requirements.txt` | Python dependencies. |
| `.env.example` | Template for the API key (copy to `.env`). |

Not committed (see `.gitignore`): the real `.env`, the `venv/`, and the generated
`scinuvo_db/` database (rebuild it with `ingest.py`).

---

## Running it locally (for testing)

1. Install Python 3.10+.
2. Create and activate a virtual environment:
   - Windows: `python -m venv venv` then `venv\Scripts\activate`
   - Linux/Mac: `python3 -m venv venv` then `source venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Set the API key (get one from console.anthropic.com):
   - Copy `.env.example` to `.env` and put the key in it, **or**
   - Set the environment variable `ANTHROPIC_API_KEY` directly.
5. Build the database: `python ingest.py`
6. Start the server: `python app.py`
7. Open `http://localhost:5000` — the widget loads and works.

---

## Deploying to production (IT team)

The included server is Flask's development server — **do not use it as-is in production.**
For a real deployment:

1. **Run behind a production WSGI server**, e.g. `waitress` (Windows) or `gunicorn` (Linux):
   - `pip install waitress` then `waitress-serve --port=5000 app:app`
2. **Serve over HTTPS** (behind Nginx / a load balancer / the host's TLS).
3. **Store the API key as a secret** on the host (environment variable), never in the code.
4. **Lock down allowed origins.** In `app.py`, set `ALLOWED_ORIGINS` to the real site
   domain(s) only (e.g. `https://scinuvo.com`).
5. **Point the widget at the backend.** In `widget.html`, set `API_URL` to the deployed
   backend URL, then embed the widget markup + script into the website's pages.
6. **Rate limits & daily cap** are in-memory (fine for one server). For multiple instances,
   move the counters in `app.py` to a shared store (e.g. Redis).

### Cost controls (already built in)
- Model: Claude Haiku (cheapest).
- `MAX_TOKENS`, `TOP_K`, `MAX_HISTORY`, `DAILY_GLOBAL_CAP`, `PER_IP_PER_MINUTE`,
  `PER_IP_PER_DAY` are configurable at the top of `app.py`.
- **Also set a hard monthly spending limit in the Anthropic console** as the final backstop.

---

## Updating product data

1. `python scrape.py` — pulls current product pages into `scraped_products.json`.
2. Review, then regenerate `scinuvo_knowledge.jsonl` (keep it customer-safe).
3. `python ingest.py` — rebuilds the database.
4. Restart the server.

To scale beyond the current products, raise `END_ID` in `scrape.py`.

---

## Before going live — checklist (important for a pharmacy)

- [ ] **Content sign-off** by a Scinuvo person with regulatory authority (the GM).
- [ ] **Fix two live-site issues found during the build:**
      (1) product-page reviews are placeholder text describing the serums as
      painkillers for headaches/back pain — correct or remove them;
      (2) the Arabic badge reads "معتمد من FDA" but should read "JFDA".
- [ ] **Set the Anthropic monthly spending cap.**
- [ ] **HTTPS + allowed-origins locked to scinuvo.com.**
- [ ] **API key stored as a host secret, not in the repo.**
- [ ] **Test with real Arabic and English questions**, including medical questions
      (it must refuse and redirect to a professional / info@scinuvo.com).

---

## Safety design notes

- The bot answers **only** from the knowledge base (grounded); it says it doesn't have a
  detail rather than invent one.
- It **refuses medical advice** and redirects to a professional or info@scinuvo.com.
- Clinical/mechanism claims and "JFDA approved" wording reflect Scinuvo's own published
  website content and should be kept in sync with what the company approves.

Contact: info@scinuvo.com · +962 79 0606 220 · scinuvo.com
