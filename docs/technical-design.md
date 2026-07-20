# EV-MarketLens Technical Design & Interview Reference

Architecture decisions, engineering trade-offs, and failure retrospectives.

---

## 1. Project Positioning

**One-liner**: A conversational EV market intelligence Agent with dual-brain architecture (Text2SQL + RAG), orchestrated by LangGraph.

**Differentiation**:
- Not "another RAG chatbot" -- has dual-brain with real intent routing
- Not "another BI dashboard" -- NL interface with chart recommendation + streaming
- Has evaluation: execution accuracy, confusion matrix, RAGAS-style metrics
- Has production engineering: safety guardrails, retry loops, fail-open patterns

---

## 2. Architecture

```
User -> FastAPI(SSE) -> LangGraph intent_router (5-layer NLU)
  +- sql:    schema_link -> gen_sql -> ensure_safe -> exec_sql <-> fix_sql -> verify_sql -> chart -> insight
  +- rag:    rag_retrieve -> rag_answer -> compose
  +- hybrid: [sql || rag] parallel -> compose(defer=True)
  +- chat:   chitchat -> END
  +- clarify: clarify -> END
```

### Why LangGraph (not if-else or LangChain agents)
- Explicit state graph: every node reads/writes typed State
- Native loops: exec->fix retry ring
- Native parallel: hybrid fan-out with deferred join
- Observable: every node appends to state.trace
- NOT using: checkpointer (dialog state lives in message table; avoids duplicate persistence)

### Why NOT checkpointer
Clarify is dialog-level (END -> new request with history), not graph-level suspend/resume. Adding MemorySaver + thread_id without interrupt() would break subsequent queries. True graph-level suspend needs interrupt() + Command(resume=...) -- deferred to future Human-in-the-loop needs.

---

## 3. Text2SQL Engineering

### Safety
- sqlglot AST traversal: walks all subtree nodes, blocks INSERT/UPDATE/DELETE/DROP
- Column names like update_time do not false-positive (AST not regex)
- with_limit() adds LIMIT 200 if missing (prevent full-table scan)
- Read-only DB connection (defense in depth)

### Retry Loop
- exec_sql failure -> error fed back to LLM -> fix_sql -> re-execute
- Max 2 retries, then graceful degradation to insight node
- Metric: retry adds ~1.7pp to first-pass accuracy

### Semantic Self-Verification (verify_sql)
- After successful execution, LLM checks "does result actually answer the question?"
- Catches: wrong filter scope, wrong aggregation dimension, mismatched time period
- FAIL-OPEN: any exception in verify -> pass through (never make system worse)
- This fixes "runs but answers wrong" -- the most dangerous failure mode

### Chart Recommendation
- Rule engine, not LLM -- deterministic, zero-cost
- Produces chart descriptor: {default_type, alternatives, dimensions, measures}
- Frontend renders from descriptor, user can switch chart type without re-querying

---

## 4. RAG Engineering

### Parent-Child Chunking
- Child chunks ~280 tokens (retrieval precision)
- Parent chunks ~900 tokens (generation context)
- Tables chunked whole (splitting tables destroys semantics)
- Overlap ~64 tokens between children

### Hybrid Recall + RRF Fusion
- Vector search (BGE-large-zh, HNSW) -> top-20
- Full-text search -> top-20
- RRF(k=60): score(d) = sum(1/(k + rank))

### Reranker + Parent Merge
- bge-reranker scores top candidates; degrades to RRF score when unavailable
- Parent merge 4 cases: dedup, adjacent merge, budget trim, conflict parallel

### Anti-Hallucination
- has_answer=false + explicit "no evidence found" when retrieval quality low
- Citations: doc_id + page_no + chunk_id + heading_path

---

## 5. Intent Routing (5-Layer NLU)

| Layer | Logic | LLM? |
|-------|-------|------|
| 1. Rule prefilter | Greeting <= 8 chars -> chat; no-data signal -> force rag | No |
| 2. LLM classify | Few-shot vector retrieval enhanced | Yes |
| 3. Entity extraction | Independent LLM call | Yes |
| 4. Slot completeness | Missing brand/time/metric -> clarify | No |
| 5. Business rules | Infrastructure/export/tech -> override sql to rag | No |

Key contract: Layer 5 only overrides sql -> rag. Never downgrades hybrid.

---

## 6. Long-term Memory

- L2 Episode: Conversation summary (only user messages, no numbers)
- L3 Profile: User preferences (whitelist: brands, metrics, segments, output_style)
- Scheduler: ThreadPoolExecutor(2) + msg_count threshold + new-message check
- Safety: Sensitive pattern filtering, untrusted-data markers, fail-open
- Concurrency: UniqueConstraint(user_id, conversation_id) as DB backstop

---

## 7. Key Engineering Decisions

| Decision | Chosen | Why not alternative |
|----------|--------|-------------------|
| LangGraph vs if-else | LangGraph | Need loops, parallel, observable state |
| Self-implement RAGAS | Self-implement | Avoid langchain dep, Chinese LLM config |
| sqlglot AST vs regex | AST | Regex bypassable via case/comments |
| Parent-child vs fixed-size | Parent-child | Precision vs context trade-off |
| verify_sql FAIL-OPEN | FAIL-OPEN | New check must never make worse |
| SQLite local | Zero-Docker start | Production uses PostgreSQL |
| No checkpointer | Intentional | Dialog state in message table |

---

## 8. Failure Retrospectives

### Text2SQL "runs but answers wrong"
- Symptom: SQL executes but returns wrong data
- Root cause: Wrong filter scope / aggregation / time period
- Fix: verify_sql semantic check + regeneration
- Lesson: Execution success != correctness

### Prompt vs Data drift (score field)
- Symptom: LLM never queries review scores
- Root cause: DOMAIN prompt said "score always NULL" -- outdated after backfill
- Fix: Update prompt + WHERE score IS NOT NULL rule
- Lesson: Prompt is implicit schema; data changes need prompt updates

### date_id format mismatch
- Symptom: Gold SQL tests returned empty
- Root cause: Gold SQL used date_id=202505 but actual IDs are sequential (1-28)
- Fix: Correct Gold SQL + update DOMAIN description
- Lesson: Evaluation dataset bugs masquerade as model failures

### Intent rag-to-sql misclassification
- Symptom: "How many charging stations?" routed to SQL
- Root cause: Classifier lacked data-source boundary description
- Fix: Explicit boundary in prompt + business rules
- Lesson: LLM needs to know what data DOES NOT exist

---

## 9. Evaluation

| Type | Method | Scale |
|------|--------|-------|
| Text2SQL | Execution result set equality (positional) | 60 samples |
| Intent | Confusion matrix + per-class P/R/F1 | 100 samples |
| RAG | RAGAS-style LLM-judge (4 metrics) | 13 samples |
| Data Quality | GE-style assertions | pytest gate |
| Unit tests | No LLM dependency | 180 passing |

Historical reports in eval/reports/ are baselines from prior runs.

---

## 10. Production

- Docker Compose: API + Frontend(Caddy HTTPS) + PG + pgvector + Redis + MinIO
- Celery workers for async RAG ingestion
- JWT with token_version (password change invalidates sessions)
- Rate limiting (0.5s/user) + payload limit (64KB)
- Backup/restore scripts
