# SmartReco architecture

```mermaid
flowchart TB
  UI[Jinja2 marketplace + JS tracker] -->|batched / keepalive| API[FastAPI]
  API --> SQL[(Users, products, events, recommendations)]
  API --> OUT[Transactional vector outbox]
  OUT --> VDB[(Chroma vector catalog)]
  SQL --> LG[LangGraph recommendation workflow]
  LG --> VDB
  LG --> MESH[Mesh API: chat + embeddings]
  LG --> SQL
  SCH[APScheduler daily digest] --> LG
  SCH --> MAIL[SMTP delivery]
```

## Recommendation workflow

```mermaid
flowchart LR
  A[Analyze weighted behavior] --> B[Semantic retrieval]
  B --> C[Metadata-aware rerank]
  C --> D[Grounded copy generation]
  D --> E[Validate product IDs]
  E --> F[Persist recommendation]
```

## Key production decisions

- Browser events are queued, capped at 50 per request, sent every 15 seconds and flushed with non-blocking `fetch(..., keepalive: true)` on exit. UUID idempotency prevents duplicate inserts.
- LLM refreshes require a weighted behavior threshold, a cooldown, and a changed behavior fingerprint. This prevents one-call-per-event waste.
- SQL is the source of truth. Product mutations commit with an outbox row; immediate sync gives a responsive demo, while retries repair partial vector failures.
- Retrieval is catalog-grounded. Mesh embeddings query active vectors, deterministic reranking adds category affinity, and generated IDs are validated against active SQL products.
- Behavioral evidence excludes sensitive traits. Persuasion is bounded by an explicit no-pressure/no-invented-claims prompt.

## Scaling path

Replace SQLite with PostgreSQL, Chroma with managed Qdrant/Pinecone, the in-process scheduler with Celery Beat, and the synchronous outbox worker with a queue consumer. Partition events by month/user, add retention rules, CSRF protection, rate limiting, consent controls, and OpenTelemetry/LangSmith tracing before public production use.
