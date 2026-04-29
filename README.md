# 🗄️ DB Designer Agent

**AI-Powered Database Schema Designer with Human-in-the-Loop Approval**

An intelligent Streamlit application that transforms natural language requirements into production-ready database schemas, complete with ERD visualization, validation, SQL generation, and sample queries.

---

## ✨ Features

- **Natural Language Input**: Describe your system in plain English (or Arabic) — the AI understands the domain and extracts entities, attributes, and relationships.
- **Interactive Suggestion Plan**: Review and approve (or modify) the proposed design before schema generation.
- **Live ERD Visualization**: Interactive entity relationship diagrams using Pyvis (draggable nodes, zoomable).
- **Human-in-the-Loop Approval**: Schema generation **only proceeds after explicit human approval**.
- **Automated Validation**: Hybrid rule-based + LLM-powered validation ensuring structural integrity and best practices.
- **Auto-Recovery**: Automatically fixes common issues (missing PKs, duplicate columns, invalid FKs, etc.).
- **3NF Normalization**: Produces clean, normalized database schemas.
- **SQLite Database Generation**: One-click downloadable `.db` file.
- **Query Generation**: Ready-to-use CRUD operations + analytical queries.
- **Session Management**: Save, load, and resume design sessions.
- **Beautiful UI**: Modern dark theme with clean, professional interface.

---

## 🛠️ Tech Stack

- **Frontend**: Streamlit
- **Backend**: Python 3
- **AI Layer**: Azure OpenAI (GPT-4o-mini)
- **Embeddings**: Azure OpenAI text-embedding-3-small
- **Schema Modeling**: Pydantic
- **ERD Visualization**: Pyvis
- **Database**: SQLite (with PostgreSQL-style syntax compatibility)
- **State Management**: Custom session persistence

---

## 📁 Project Structure

```
DB Designer Agent/
├── app.py                          # Main Streamlit application
├── models.py                       # Pydantic data models
├── services/
│   ├── orchestrator.py             # Pipeline orchestration
│   ├── llm_service.py              # LLM client factory
│   └── __init__.py
├── agents/
│   ├── requirement_analyzer.py
│   ├── suggestion_agent.py
│   ├── schema_designer.py
│   ├── validation_agent.py
│   ├── query_generator.py
│   └── __init__.py
├── validators.py                   # Rule-based validation & recovery
├── erd_visualizer.py               # ERD generation + SQL DDL
├── report_generator.py             # Final report
├── memory.py                       # Session persistence
├── utils.py                        # Helper utilities
└── .env                            # Environment variables
```

---

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd db-designer-agent
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the root directory:

```env
AZURE_OPENAI_API_KEY=your_azure_openai_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o-mini
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
```

### 4. Run the Application

```bash
streamlit run app.py
```

---

## 📋 How It Works

1. **Describe Requirements** — Enter your system description in natural language.
2. **AI Analysis** — The agent analyzes entities, attributes, and relationships.
3. **Suggestion Plan** — Review the proposed design + interactive ERD.
4. **Human Approval** — Approve, reject, or request modifications.
5. **Schema Generation** — AI generates a normalized `DatabaseSchema`.
6. **Validation & Recovery** — Automatic fixing of common design issues.
7. **Final Output**:
   - Interactive ERD
   - Full SQL DDL (SQLite compatible)
   - Downloadable `.db` file
   - CRUD + Analytical queries
   - Validation report

---

## 🎯 Example Use Cases

- School Management System
- E-Commerce Platform
- Hospital Management System
- HR & Payroll System
- Inventory Management
- Any custom relational database design

---

## 🔧 Key Capabilities

- **Robust Validation**: Prevents common anti-patterns and enforces best practices.
- **Modification Support**: Change the plan via natural language instructions.
- **Domain Awareness**: Understands context (education, healthcare, finance, etc.).
- **Audit Trail**: Tracks all modifications and approvals.
- **Fallback Mechanisms**: Graceful degradation when LLM responses are imperfect.

---

## 🧪 Development

### Running Tests (Future)

```bash
pytest tests/
```

### Adding New Features

The architecture is highly modular:
- Add new agents in the `agents/` folder
- Extend models in `models.py`
- Update pipeline flow in `orchestrator.py`

---

## 📄 License

This project is licensed under the MIT License.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!

1. Fork the project
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📬 Support

If you have any questions or suggestions, feel free to open an issue.
