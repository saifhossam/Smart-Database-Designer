# 🗄️ DB Designer Agent System

An **AI-powered, agent-based database schema designer** with Human-in-the-Loop approval and live ERD visualization.

---

## 🏗 Architecture Overview

```
User Input (NL)
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 1: Requirement Analyzer Agent                        │
│  → Extracts entities, attributes, relationships             │
│  → Uses Azure OpenAI (GPT-4o) + structured JSON output      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼ (+ RAG context from Azure Search)
┌─────────────────────────────────────────────────────────────┐
│  Phase 2: Suggestion / Planning Agent                       │
│  → Proposes full entity model with attributes               │
│  → Suggests optional features (RBAC, audit logs, etc.)      │
│  → Generates live ERD via Pyvis                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  ⏸  HUMAN APPROVAL GATE  │  ← Approve or Reject
            │  ❌ NO schema until here  │
            └──────────┬───────────────┘
                       │ (approved)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 3: Schema Designer Agent                             │
│  → Tables, columns, data types, PK/FK, indexes              │
│  → 3NF normalised, junction tables for M:N                  │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 4: Validation Agent                                  │
│  → Static checks (missing PK, broken FK refs)               │
│  → LLM-based deep validation (3NF, data types, indexes)     │
│  → Auto-applies corrections if errors found                 │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 5: Query Generator Agent                             │
│  → CRUD queries for every table                             │
│  → 5+ analytical queries with JOINs and aggregations        │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
            ┌──────────────────────────┐
            │  Output: SQL DDL + JSON  │
            │  + Queries + ERD diagram │
            └──────────────────────────┘
```

---

## 📁 Project Structure

```
db_designer_agent/
├── app.py                        # Streamlit UI (main entry point)
├── cli.py                        # CLI interface (alternative)
├── orchestrator.py               # Pipeline controller + approval gate
├── models.py                     # Pydantic data models
├── llm_client.py                 # Azure OpenAI client factory
├── tests.py                      # pytest test suite
├── requirements.txt
├── .env.example                  # Environment variable template
│
├── agents/
│   ├── __init__.py
│   ├── requirement_analyzer.py   # Agent 1: NL → structured analysis
│   ├── suggestion_agent.py       # Agent 2: analysis → design plan
│   ├── schema_designer.py        # Agent 3: plan → schema (post-approval)
│   ├── validation_agent.py       # Agent 4: schema validation + correction
│   └── query_generator.py        # Agent 5: schema → SQL queries
│
├── memory/
│   ├── __init__.py
│   └── session_store.py          # Session persistence + approval logging
│
├── rag/
│   ├── __init__.py
│   └── semantic_search.py        # Azure Search + ChromaDB fallback
│
└── utils/
    ├── __init__.py
    └── erd_visualizer.py         # Pyvis + Plotly ERD generation + SQL DDL
```

---

## ⚙️ Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your Azure OpenAI and Azure Search credentials
```

Required variables:
```
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002
```

Optional (RAG enrichment):
```
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_API_KEY=...
AZURE_SEARCH_INDEX_NAME=db-schemas-index
```

### 3. Run the application

**Streamlit UI (recommended):**
```bash
streamlit run app.py
```

**CLI:**
```bash
python cli.py
python cli.py --input "I need an e-commerce system with products, orders, and customers"
python cli.py --session <session_id>   # Resume a previous session
```

### 4. Run tests

```bash
pytest tests.py -v
```

---

## 🔄 Pipeline Flow

```
User Input
    │
    ▼  run_pre_approval_pipeline()
Requirement Analysis
    │
    ▼  + RAG context
Suggestion Plan + Live ERD
    │
    ▼  ⏸ raises ApprovalRequired
UI shows ERD + Approve / Reject buttons
    │
    ├── reject → reset session
    │
    └── approve → run_post_approval_pipeline()
                      │
                      ▼
                  Schema Design
                      │
                      ▼
                  Validation (+ auto-correct)
                      │
                      ▼
                  Query Generation
                      │
                      ▼
                  Index in RAG store
                      │
                      ▼
                  Output: SQL DDL + JSON + Queries
```

---

## 🛡 Risk Handling

| Risk | Mitigation |
|------|-----------|
| Over-engineering | LLM instructed to prefer lean, domain-appropriate schemas |
| Missing relationships | Static validator checks all FK references; LLM deep-checks |
| Wrong normalisation | System prompt enforces 3NF; validation agent flags violations |
| Incorrect data types | Explicit type mapping in all prompts (UUID, VARCHAR(n), DECIMAL(p,s)…) |
| Missing constraints | Every PK/FK/UNIQUE/NOT NULL enforced by prompt + static checks |
| Scalability | Modular tables required; single-table designs flagged as errors |
| No iteration support | Session memory + iteration counter; reload previous sessions via CLI/UI |

---

## 💡 Key Design Decisions

1. **ApprovalRequired exception** — the pre-approval pipeline raises this exception to force the UI/CLI to pause and collect user input. Schema generation is **physically impossible** without catching this and calling `approve_plan()`.

2. **Layered RAG** — Azure Search (primary) → ChromaDB (local fallback) → keyword search (zero-dependency fallback). The system always works, even offline.

3. **Static + LLM validation** — deterministic rules catch structural errors cheaply; LLM adds semantic validation (3NF, type correctness).

4. **Session persistence** — every state transition is saved to disk. Sessions can be resumed by ID across restarts.

5. **Single-responsibility agents** — each agent does exactly one thing and receives/returns a typed Pydantic model. This makes them independently testable and replaceable.
