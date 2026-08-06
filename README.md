# SmartReco — Behavioral AI Recommendation Agent

SmartReco is a working server-rendered learning marketplace that observes meaningful user behavior, retrieves real catalog items semantically, and creates persuasive—but grounded and ethical—recommendation narratives. Every AI operation, including embeddings, goes through the mandatory Mesh API.

## Competition coverage

| Requirement | Implementation |
|---|---|
| Email/password + roles | JWT HTTP-only cookie; user/admin roles |
| Product CRUD + dual-write | SQL source of truth + transactional vector outbox + Chroma sync |
| Rich tracking | Views, searches, clicks, dwell and cart signal schema; batches of 50; non-blocking keepalive requests |
| Agentic RAG | LangGraph analyze → hybrid retrieve → diversity rerank → generate → SQL ID validation |
| Efficient AI use | Weighted trigger, 20-minute cooldown, behavior fingerprint cache |
| Persuasive output | Mesh-generated narrative + visible “why this” evidence and node trace |
| Dual-write ops | Per-product retry, retry-all failed, last Mesh/vector error surfaced in admin |
| Scheduled delivery | APScheduler 3 PM daily digest through SMTP |
| Observability-ready | Explicit named LangGraph nodes; set `LANGCHAIN_TRACING_V2=true` + LangSmith key for tracing |

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams, tradeoffs, and scaling.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Put your rsk_... key in .env
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Admin credentials come from `.env`; change them before use. To seed demo courses (this calls Mesh embeddings):

```bash
python scripts/seed.py
```

## Environment

`MESH_API_KEY` is mandatory. `MESH_CHAT_MODEL` and `MESH_EMBEDDING_MODEL` must be model identifiers available through Mesh. SMTP is optional; when `SMTP_HOST` is blank the scheduled task safely skips email. For SendGrid set `SMTP_HOST=smtp.sendgrid.net`, `SMTP_USERNAME=apikey`, `SMTP_PASSWORD=<SendGrid API key>`, and a verified `SMTP_FROM`. For deployment set a strong `SECRET_KEY`, HTTPS, and change cookie `secure=True`.

## How recommendations refresh

Events carry weights: view 1–2, search/click 3, cart 6. A refresh only runs after the configurable threshold, outside the cooldown, and when the fingerprint of recent behavior changed. The latest stored recommendation remains visible between refreshes. This makes output stable and keeps model cost proportional to meaningful intent.

## Product consistency

Admin writes commit the product and an outbox record in the same SQL transaction. A vector sync is attempted immediately for the demo. Failed jobs remain unprocessed, increment attempts, and can be retried by the scheduler. Archive creates a delete job, preventing stale semantic retrieval.

## Tests and checks

```bash
python -m compileall -q app scripts tests
pytest
```

The repository includes the official `.github/workflows/smartreco-checks.yml` from the challenge portal. Add GitHub Actions secrets `MESH_API_KEY` and `SUBMISSION_TOKEN`. Never commit `.env`.

For the LangSmith observability bonus, set `LANGCHAIN_TRACING_V2=true` plus `LANGCHAIN_API_KEY` and `LANGCHAIN_PROJECT` in `.env`.

## Demo video

A judge walkthrough is included at [`demos/smartreco-judge-demo.mp4`](demos/smartreco-judge-demo.mp4) and also attached to the GitHub Release.

Suggested live demo flow:

1. Sign in as admin and add several courses; show `vector_status=synced`.
2. Register as a user, search “agentic AI,” inspect advanced AI courses, and linger on them.
3. After enough signal, refresh the page to reveal the adaptive narrative, grounded cards, and agent workflow trace.
4. Show LangSmith traces (project `smartreco`) and optional SendGrid digest from `/admin`.
5. Change behavior toward product leadership and demonstrate the updated path.

## Responsible-use notes

The agent uses explicit on-site behavior, does not infer protected or sensitive characteristics, does not create fake urgency, and validates every recommendation against the active catalog. A real deployment should add tracking consent, data export/deletion, retention limits, audit logs, rate limiting, CSRF protection, and an unsubscribe mechanism.
