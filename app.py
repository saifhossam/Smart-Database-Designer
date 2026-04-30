"""
DB Designer Agent – Streamlit UI
==================================
Interactive interface with:
  • Natural-language input
  • Live ERD visualization (Pyvis embedded in iframe)
  • Human-in-the-loop approval buttons
  • Step-by-step pipeline progress
  • Clean, readable outputs (no raw JSON tabs)
"""
from __future__ import annotations
import os
import logging

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="DB Designer Agent",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from models import SessionState
from memory import load_session, list_sessions, clear_sessions
from services.orchestrator import (
    run_pre_approval_pipeline,
    run_post_approval_pipeline,
    approve_plan,
    reject_plan,
    modify_plan,
    ApprovalRequired,
)
from utils import (
    build_erd_html_from_plan,
    build_erd_html_from_schema,
    generate_sqlite_ddl,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Space+Grotesk:wght@300;400;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Space Grotesk', sans-serif; }
.stApp { background: linear-gradient(135deg, #0a0f1e 0%, #0d1b2a 50%, #0a1628 100%); }
section[data-testid="stSidebar"] { background: #070d1a !important; border-right: 1px solid #1e3a5f; }

.agent-card {
    background: rgba(30,58,95,0.25);
    border: 1px solid rgba(79,195,247,0.2);
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1rem;
    backdrop-filter: blur(10px);
}
.agent-card h3 { color: #4fc3f7; margin: 0 0 0.5rem; font-size: 1rem; }
.agent-card p  { color: #a0c4e8; margin: 0; font-size: 0.88rem; line-height: 1.5; }

.status-pill {
    display: inline-block; padding: 3px 14px; border-radius: 20px;
    font-size: 0.78rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;
}
.status-init       { background:#1e3a5f; color:#4fc3f7; }
.status-analyzing  { background:#2d3a1e; color:#a3e635; }
.status-suggesting { background:#3a2d1e; color:#f0a500; }
.status-awaiting   { background:#3a1e2d; color:#f06292; }
.status-approved   { background:#1e3a26; color:#4ade80; }
.status-rejected   { background:#3a1e1e; color:#f87171; }
.status-complete   { background:#1e2d3a; color:#60a5fa; }

.approval-banner {
    background: linear-gradient(90deg, rgba(240,165,0,0.15), rgba(240,165,0,0.05));
    border: 1px solid rgba(240,165,0,0.4); border-left: 4px solid #f0a500;
    border-radius: 8px; padding: 1.2rem 1.5rem; margin: 1rem 0;
    color: #f0a500; font-weight: 600; font-size: 1rem;
}

.stButton > button {
    border-radius: 8px !important; font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important; letter-spacing: 0.03em !important;
    transition: all 0.2s ease !important;
}

pre, code { font-family: 'JetBrains Mono', monospace !important; font-size: 0.82rem !important; }
h1 { color: #e0f4ff !important; font-weight: 700 !important; }
h2 { color: #b3d9f5 !important; font-weight: 600 !important; }
h3 { color: #7ec8e3 !important; }

[data-testid="metric-container"] {
    background: rgba(30,58,95,0.3) !important;
    border: 1px solid rgba(79,195,247,0.2) !important;
    border-radius: 10px !important; padding: 0.8rem !important;
}

hr { border-color: rgba(79,195,247,0.15) !important; margin: 1.5rem 0 !important; }

.stTabs [data-baseweb="tab-list"] { gap: 4px; background: transparent; }
.stTabs [data-baseweb="tab"] {
    background: rgba(30,58,95,0.3); border-radius: 8px 8px 0 0;
    color: #a0c4e8; font-weight: 600;
}
.stTabs [aria-selected="true"] { background: rgba(79,195,247,0.2); color: #4fc3f7 !important; }
.stAlert { border-radius: 10px !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Session helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_session() -> SessionState:
    if "session" not in st.session_state:
        st.session_state["session"] = SessionState()
    return st.session_state["session"]


def set_session(s: SessionState) -> None:
    st.session_state["session"] = s


def clear_session() -> None:
    """Completely clear ALL Streamlit session state and start fresh."""
    st.session_state.clear()
    st.session_state["session"] = SessionState()


def status_pill(status: str) -> str:
    mapping = {
        "init":               ("status-init",      "⬜ Init"),
        "analyzing":          ("status-analyzing", "🔍 Analyzing"),
        "suggesting":         ("status-suggesting","💡 Suggesting"),
        "awaiting_approval":  ("status-awaiting",  "⏸ Awaiting Approval"),
        "approved":           ("status-approved",  "✅ Approved"),
        "rejected":           ("status-rejected",  "❌ Rejected"),
        "designing":          ("status-approved",  "🏗 Designing"),
        "validating":         ("status-approved",  "🔒 Validating"),
        "generating_queries": ("status-approved",  "📝 Generating Queries"),
        "complete":           ("status-complete",  "🏁 Complete"),
    }
    cls, label = mapping.get(status, ("status-init", status))
    return f'<span class="status-pill {cls}">{label}</span>'


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

def render_sidebar(session: SessionState) -> None:
    with st.sidebar:
        st.markdown("## 🗄️ DB Designer Agent")
        st.markdown("---")

        st.markdown("### 🔄 Pipeline Status")
        st.markdown(status_pill(session.status), unsafe_allow_html=True)
        st.markdown("")

        # Steps checklist
        steps = [
            ("1. Requirement Analysis", session.requirement_analysis is not None),
            ("2. Suggestion Plan",      session.suggestion_plan is not None),
            ("3. Human Approval",       session.approval_record is not None),
            ("4. Schema Design",        session.database_schema is not None),
            ("5. Validation",           session.validation_result is not None),
            ("6. Query Generation",     session.query_set is not None),
        ]
        for label, done in steps:
            colour = "#4ade80" if done else "#4a5568"
            icon = "✅" if done else "⬜"
            st.markdown(
                f"<p style='color:{colour};margin:4px 0;font-size:0.88rem'>{icon} {label}</p>",
                unsafe_allow_html=True,
            )

        st.markdown("---")

        if session.session_id:
            st.markdown(f"**Session:** `{session.session_id[:8]}…`")
            st.markdown(f"**Iteration:** {session.iteration}")

        st.markdown("---")

        # Action buttons
        col_new, col_clear, col_saved = st.columns(3)
        with col_new:
            if st.button("🔄 New", use_container_width=True):
                clear_session()
                st.rerun()

        with col_clear:
            if st.button("🗑️ Clear", use_container_width=True):
                clear_session()
                st.success("Session cleared!")
                st.rerun()

        with col_saved:
            if st.button("🧹 Clear Saved", use_container_width=True):
                clear_sessions()
                st.success("Saved sessions cleared!")
                st.rerun()

        st.markdown("")

        # Recent sessions
        st.markdown("### 📚 Recent Sessions")
        recent = list_sessions()[:5]
        if not recent:
            st.caption("No saved sessions yet.")
        for s in recent:
            label = (s["user_input"][:26] + "…") if len(s["user_input"]) > 26 else s["user_input"]
            status_icon = "✅" if s["status"] == "complete" else "⏸" if s["status"] == "awaiting_approval" else "🔄"
            if st.button(f"{status_icon} {label}", key=f"load_{s['session_id']}", use_container_width=True):
                loaded = load_session(s["session_id"])
                if loaded:
                    set_session(loaded)
                    st.rerun()

        st.markdown("---")
        st.caption("🔒 Human-in-the-Loop • 3NF Schema • Azure AI Search RAG")


# ─────────────────────────────────────────────────────────────────────────────
# Input phase
# ─────────────────────────────────────────────────────────────────────────────

def render_input_phase(session: SessionState) -> None:
    st.markdown("## 🧠 Describe Your Database Requirements")

    example_options = {
        "🏫 School Management System": "I need a school management system with students, teachers, courses, classes, enrollments, grades, and attendance tracking.",
        "🛒 E-Commerce Platform": "Build a complete e-commerce platform with products, categories, customers, orders, payments, reviews, and inventory management.",
        "🏥 Hospital Management": "Design a hospital system with patients, doctors, departments, appointments, medical records, prescriptions, and billing.",
        "👔 HR & Payroll System": "Create an HR system with employees, departments, positions, salaries, leave management, performance reviews, and payroll.",
        "✍️ Custom Input": "",
    }

    col1, col2 = st.columns([2, 1])
    with col1:
        selected = st.selectbox("📋 Quick start (optional)", list(example_options.keys()))
        user_input = st.text_area(
            "Describe your system in natural language",
            value=example_options[selected],
            height=140,
            placeholder="e.g. I need a school management system with students, teachers...",
        )
    with col2:
        st.markdown("### 💡 Tips")
        st.info(
            "- Mention **all entities** you can think of\n"
            "- Describe **relationships** between them\n"
            "- Mention any **special features** (roles, logs, audit trails, etc.)\n"
            "- The AI will automatically enrich and normalize your requirements"
        )

    st.markdown("")
    if st.button("🚀 Analyze & Generate Plan", type="primary", use_container_width=True):
        if not user_input.strip():
            st.warning("Please describe your system first.")
            return
        _check_env()
        with st.spinner("🔍 Analyzing requirements and generating suggestions…"):
            try:
                run_pre_approval_pipeline(user_input.strip(), session)
                st.rerun()
            except ApprovalRequired as ar:
                set_session(ar.session)
                st.rerun()
            except Exception as exc:
                st.error(f"Pipeline error: {exc}")
                logger.exception("Pre-approval pipeline failed")


# ─────────────────────────────────────────────────────────────────────────────
# Suggestion / approval phase
# ─────────────────────────────────────────────────────────────────────────────

def render_suggestion_phase(session: SessionState) -> None:
    plan = session.suggestion_plan
    if plan is None:
        st.error("No suggestion plan found. Please restart.")
        return

    st.markdown("""
    <div class="approval-banner">
    ⏸  <strong>HUMAN APPROVAL REQUIRED</strong> — Please review the proposed design below carefully.<br>
    Schema generation will <strong>NOT</strong> proceed without your approval.
    </div>
    """, unsafe_allow_html=True)

    col_plan, col_erd = st.columns([1, 1], gap="large")

    with col_plan:
        st.markdown("### 📋 Suggested Design")
        st.markdown("#### 🗃 Entities")
        for entity in plan.suggested_entities:
            with st.expander(f"📦 **{entity.name}**  ({len(entity.attributes)} attributes)", expanded=False):
                if entity.description:
                    st.caption(entity.description)
                for attr in entity.attributes:
                    badges = []
                    if attr.is_primary_key: badges.append("🔑 PK")
                    if attr.is_foreign_key: badges.append("🔗 FK")
                    if not attr.is_nullable: badges.append("∗")
                    badge_str = "  `" + "  ".join(badges) + "`" if badges else ""
                    st.markdown(f"- **{attr.name}**: `{attr.data_type}`{badge_str}")

        st.markdown("#### 🔗 Relationships")
        for rel in plan.suggested_relationships:
            arrow = {"one-to-one": "1──1", "one-to-many": "1──N", "many-to-many": "N──M"}.get(
                rel.relationship_type, "──"
            )
            st.markdown(f"- **{rel.from_entity}** `{arrow}` **{rel.to_entity}** _{rel.label or ''}_")

        if plan.optional_features:
            st.markdown("#### ✨ Optional Features")
            for feat in plan.optional_features:
                with st.expander(f"⚙️ {feat.name}"):
                    st.write(feat.description)
                    if feat.entities_involved:
                        st.caption(f"Involves: {', '.join(feat.entities_involved)}")

        if plan.rationale:
            with st.expander("🧠 Design Rationale"):
                st.write(plan.rationale)

    with col_erd:
        st.markdown("### 🌐 Live ERD Preview")
        st.caption("Drag nodes to rearrange • Zoom with mouse wheel")
        erd_html = build_erd_html_from_plan(plan)
        components.html(erd_html, height=530, scrolling=False)

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entities", len(plan.suggested_entities))
    c2.metric("Relationships", len(plan.suggested_relationships))
    c3.metric("Total Attributes", sum(len(e.attributes) for e in plan.suggested_entities))
    c4.metric("Optional Features", len(plan.optional_features))

    # Modification section
    st.markdown("### ✍️ Modify Plan")
    modify_instruction = st.text_input(
        "Modification command",
        placeholder="modify: add Inventory table with product_id, stock_count, last_updated",
        key=f"modify_{session.session_id}",
    )
    if st.button("🔄 Apply Modification", use_container_width=True):
        if modify_instruction.strip():
            try:
                updated = modify_plan(session, modify_instruction)
                set_session(updated)
                st.success("Plan updated successfully.")
                st.rerun()
            except Exception as exc:
                st.error(f"Modification failed: {exc}")

    if session.modification_history:
        st.markdown("#### 📝 Modification History")
        for i, change in enumerate(session.modification_history, 1):
            st.markdown(f"{i}. {change}")

    st.markdown("### 🔐 Your Decision")
    st.warning("**Carefully review the ERD and entities before approving.**")

    col_approve, col_reject, col_clear, _ = st.columns([1, 1, 1, 1])
    with col_approve:
        if st.button("✅ APPROVE — Generate Schema", type="primary", use_container_width=True):
            updated = approve_plan(session, notes="Approved via Streamlit UI")
            set_session(updated)
            with st.spinner("🏗 Designing full schema..."):
                try:
                    completed = run_post_approval_pipeline(updated)
                    set_session(completed)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Post-approval error: {exc}")

    with col_reject:
        if st.button("❌ REJECT — Start Over", use_container_width=True):
            reject_plan(session, notes="Rejected via Streamlit UI")
            clear_session()
            st.rerun()

    with col_clear:
        if st.button("🗑️ Clear Session", use_container_width=True):
            clear_session()
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Results phase (Improved Validation Report - Reordered)
# ─────────────────────────────────────────────────────────────────────────────

def render_results_phase(session: SessionState) -> None:
    schema = session.database_schema
    validation = session.validation_result
    queries = session.query_set

    st.markdown("## 🏁 Database Design Complete")
    st.success("✅ Your database schema has been successfully designed, validated, and enriched with queries!")

    if session.db_file_path:
        try:
            with open(session.db_file_path, "rb") as f:
                db_bytes = f.read()
            st.download_button(
                "⬇️ Download SQLite Database (.db)",
                data=db_bytes,
                file_name=os.path.basename(session.db_file_path),
                mime="application/x-sqlite3",
            )
        except Exception:
            st.warning("SQLite file not available for download.")

    # Metrics
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Tables", len(schema.tables) if schema else 0)
    c2.metric("Total Columns", sum(len(t.columns) for t in schema.tables) if schema else 0)
    c3.metric("Normalization", schema.normalization_level if schema else "—")
    c4.metric("Validation Issues", len(validation.issues) if validation else 0)
    c5.metric("Queries Generated", 
              (sum(len(v) for v in queries.crud_queries.values()) + len(queries.analytical_queries)) if queries else 0)

    st.markdown("---")

    tab_erd, tab_schema, tab_sql, tab_validation, tab_queries = st.tabs([
        "🌐 ERD", "🗃 Schema", "📜 SQL DDL", "✅ Validation Report", "🔍 Queries"
    ])

    # ERD Tab
    with tab_erd:
        st.markdown("### Entity Relationship Diagram")
        if schema and schema.tables:
            erd_html = build_erd_html_from_schema(schema)
            components.html(erd_html, height=650, scrolling=False)
        else:
            st.warning("No schema available for ERD.")

    # Schema Tab
    with tab_schema:
        st.markdown("### Database Tables")
        for table in schema.tables if schema else []:
            with st.expander(f"🗄 **{table.name}**  ({len(table.columns)} columns)", expanded=False):
                if table.description:
                    st.caption(table.description)
                df = pd.DataFrame([{
                    "Column": c.name,
                    "Type": c.data_type,
                    "Constraints": ", ".join(c.constraints) if c.constraints else "—",
                    "References": c.references or "—",
                    "Description": c.description or "",
                } for c in table.columns])
                st.dataframe(df, use_container_width=True, hide_index=True)

                if table.indexes:
                    st.markdown("**Indexes:**")
                    for idx in table.indexes:
                        st.code(idx, language="sql")

    # SQL DDL Tab
    with tab_sql:
        st.markdown("### SQLite DDL Script")
        ddl = session.sql_schema or generate_sqlite_ddl(schema)
        st.code(ddl, language="sql")
        st.download_button("⬇️ Download schema.sql", data=ddl, file_name="schema.sql", mime="text/plain")

    # ==================== VALIDATION REPORT TAB (REORDERED) ====================
    with tab_validation:
        st.markdown("### 🖨 Validation Report")

        if not validation:
            st.info("No validation results available yet.")
            return

        # Schema Validation Status
        if validation.is_valid:
            st.success("**Schema Validation Passed**")


        # 2. Suggestions for Improvement — SECOND
        suggestions = []
        if getattr(validation, 'llm_suggestions', None):
            suggestions.extend(validation.llm_suggestions)
        
        # Collect informational issues that have suggestions
        info_issues = [i for i in validation.issues if i.severity == "info" and getattr(i, 'suggestion', None)]
        for issue in info_issues:
            suggestions.append(issue)

        if suggestions:
            st.markdown("#### 💡 Suggestions for Improvement")
            for sug in suggestions:
                location = ""
                if hasattr(sug, 'table') and sug.table:
                    location = f"[{sug.table}]"
                    if hasattr(sug, 'column') and sug.column:
                        location += f".{sug.column}"
                
                message = getattr(sug, 'message', str(sug))
                suggestion_text = getattr(sug, 'suggestion', "")

                with st.container():
                    st.markdown(f"""
                    <div style="background: #2a2a1f; border-left: 5px solid #f0a500; padding: 12px 16px; 
                                border-radius: 6px; margin: 8px 0;">
                        <strong>{location}</strong> {message}<br>
                        <span style="color:#ffd700;">→ Suggestion:</span> {suggestion_text}
                    </div>
                    """, unsafe_allow_html=True)

        # 3. Warnings — THIRD
        warnings = [i for i in validation.issues if i.severity == "warning"]
        if warnings:
            st.markdown("#### 🟡 Warnings")
            for issue in warnings:
                loc = f"**[{issue.table}]**" if issue.table else ""
                if issue.column:
                    loc += f".**{issue.column}**"
                st.warning(f"{loc} — {issue.message}")

        # 4. Errors — LAST
        errors = [i for i in validation.issues if i.severity == "error"]
        if errors:
            st.markdown("#### 🔴 Attention")
            for issue in errors:
                loc = f"**[{issue.table}]**" if issue.table else ""
                if issue.column:
                    loc += f".**{issue.column}**"
                st.error(f"{loc} — {issue.message}")

    # Queries Tab
    with tab_queries:
        st.markdown("### Generated SQL Queries")
        if not queries:
            st.info("No queries generated yet.")
            return

        q_crud, q_analytical = st.tabs(["🔧 CRUD Operations", "📊 Analytical Queries"])

        with q_crud:
            for table_name, ops in queries.crud_queries.items():
                with st.expander(f"📋 `{table_name}`", expanded=False):
                    if isinstance(ops, dict):
                        for name, sql in ops.items():
                            st.markdown(f"**{name.replace('_', ' ').title()}**")
                            st.code(sql, language="sql")
                    else:
                        for sql in ops if isinstance(ops, list) else []:
                            st.code(sql, language="sql")

        with q_analytical:
            if queries.analytical_queries:
                for q in queries.analytical_queries:
                    with st.expander(f"📊 {q.get('name', 'Analytical Query')}", expanded=False):
                        if q.get("description"):
                            st.caption(q["description"])
                        st.code(q.get("sql", ""), language="sql")
            else:
                st.info("No analytical queries were generated for this schema.")

    st.markdown("---")
    col1, col2, _ = st.columns([1, 1, 2])
    with col1:
        if st.button("🔄 Design Another Database", use_container_width=True):
            clear_session()
            st.rerun()
    with col2:
        if st.button("🗑️ Clear Session", use_container_width=True):
            clear_session()
            st.rerun()
            
# ─────────────────────────────────────────────────────────────────────────────
# Environment check
# ─────────────────────────────────────────────────────────────────────────────

def _check_env() -> None:
    missing = [k for k in ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"] if not os.getenv(k)]
    if missing:
        st.error(f"Missing environment variables: `{'`, `'.join(missing)}`")
        st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    session = get_or_create_session()
    render_sidebar(session)

    st.markdown(
        "<h1 style='text-align:center;margin-bottom:0'>🗄️ DB Designer Agent</h1>"
        "<p style='text-align:center;color:#4fc3f7;margin-top:4px;font-size:1.05rem'>"
        "AI-Powered Database Schema Designer with Human-in-the-Loop Approval</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    status = session.status

    if status in ("init", "rejected"):
        render_input_phase(session)

    elif status == "awaiting_approval":
        render_suggestion_phase(session)

    elif status == "complete":
        render_results_phase(session)

    elif status in ("analyzing", "suggesting", "designing", "validating", "generating_queries"):
        st.info(f"Pipeline is running... Current stage: **{status}**")
        st.spinner("Please wait while the agent works...")

    elif status == "approved":
        with st.spinner("Continuing post-approval pipeline..."):
            try:
                completed = run_post_approval_pipeline(session)
                set_session(completed)
                st.rerun()
            except Exception as exc:
                st.error(f"Error: {exc}")
    else:
        render_input_phase(session)


if __name__ == "__main__":
    main()
