"""Pipeline orchestrator service for DB Designer Agent."""
from __future__ import annotations
import logging

from models import SessionState
from agents import (
    run_requirement_analyzer,
    run_suggestion_agent,
    run_schema_designer,
    run_validation_agent,
    run_query_generator,
    run_plan_modifier,
)
from memory import save_session, record_approval
from utils import create_sqlite_database, generate_final_report
from validators import production_validation

logger = logging.getLogger(__name__)


class ApprovalRequired(Exception):
    """Raised when the pipeline reaches the human-in-the-loop gate."""

    def __init__(self, session: SessionState):
        self.session = session
        super().__init__("Awaiting human approval before schema generation.")


class PipelineError(Exception):
    """Generic pipeline error with session context."""

    def __init__(self, message: str, session: SessionState):
        self.session = session
        super().__init__(message)


def run_pre_approval_pipeline(user_input: str, session: SessionState) -> SessionState:
    """Run requirement analysis and suggestion planning."""
    session.user_input = user_input
    session.status = "analyzing"
    session.add_message("user", user_input)
    save_session(session)

    logger.info("[Phase 1] Requirement Analysis…")
    session.requirement_analysis = run_requirement_analyzer(user_input)
    session.status = "suggesting"
    save_session(session)

    logger.info("[Phase 2] Suggestion Planning…")
    session.suggestion_plan = run_suggestion_agent(session.requirement_analysis)
    session.status = "awaiting_approval"
    session.add_message("assistant", "Suggestion plan ready. Awaiting human approval.")
    save_session(session)

    raise ApprovalRequired(session)


def modify_plan(session: SessionState, modification_instruction: str) -> SessionState:
    """Apply a human modification request to the current suggestion plan."""
    if session.suggestion_plan is None or session.requirement_analysis is None:
        raise PipelineError("No suggestion plan or requirement analysis available to modify.", session)

    cleaned = modification_instruction.strip()
    if cleaned.lower().startswith("modify:"):
        cleaned = cleaned.split(":", 1)[1].strip()

    if not cleaned:
        raise PipelineError("Modification instruction may not be empty.", session)

    session.add_message("user", modification_instruction)
    session.suggestion_plan = run_plan_modifier(
        session.suggestion_plan,
        cleaned,
        session.requirement_analysis,
    )
    session.modification_history.append(cleaned)
    session.iteration += 1
    session.status = "awaiting_approval"
    session.add_message("assistant", "Suggestion plan updated after modification.")
    save_session(session)
    return session


def run_post_approval_pipeline(session: SessionState) -> SessionState:
    """Run schema design, validation, query generation, and indexing."""
    if session.status != "approved":
        raise PipelineError(
            f"Expected status 'approved', got '{session.status}'.", session
        )
    if session.suggestion_plan is None:
        raise PipelineError("No suggestion plan found — run pre-approval pipeline first.", session)

    logger.info("[Phase 3] Schema Design…")
    session.status = "designing"
    save_session(session)
    session.database_schema = run_schema_designer(session.suggestion_plan)

    session.database_schema, vreport = production_validation(
        session.suggestion_plan, session.database_schema
    )
    logger.info("Orchestrator production validation: %s", vreport)
    save_session(session)

    logger.info("[Phase 4] Validation Agent…")
    session.status = "validating"
    save_session(session)
    session.validation_result = run_validation_agent(
        session.database_schema,
        domain=session.requirement_analysis.domain if session.requirement_analysis else "unknown",
    )

    if session.validation_result and session.validation_result.corrected_schema:
        logger.info("Applying corrected schema from Validation Agent.")
        session.database_schema = session.validation_result.corrected_schema
        session.validation_result = run_validation_agent(
            session.database_schema,
            domain=session.requirement_analysis.domain if session.requirement_analysis else "unknown",
        )

    save_session(session)

    logger.info("[Phase 5] Query Generation…")
    session.status = "generating_queries"
    save_session(session)
    session.query_set = run_query_generator(session.database_schema)

    logger.info("[Phase 6] Create SQLite database file…")
    session.db_file_path, session.sql_schema = create_sqlite_database(
        session.database_schema,
        session.user_input or 'db_design',
    )

    logger.info("[Phase 7] Final Report…")
    session.final_report = generate_final_report(
        session_id=session.session_id,
        user_input=session.user_input,
        requirement_analysis=session.requirement_analysis,
        suggestion_plan=session.suggestion_plan,
        schema=session.database_schema,
        validation_result=session.validation_result,
        query_set=session.query_set,
    )
    if session.db_file_path:
        session.final_report["db_file_path"] = session.db_file_path
    if session.sql_schema:
        session.final_report["sql_schema"] = session.sql_schema
    if session.modification_history:
        session.final_report["modification_history"] = session.modification_history

    session.add_message("system", "Final report generated.")

    session.status = "complete"
    session.add_message("assistant", "Schema generation complete.")
    save_session(session)

    logger.info("Pipeline complete for session %s", session.session_id)
    return session


def approve_plan(session: SessionState, notes: str = "") -> SessionState:
    record_approval(session, "approve", notes=notes)
    return session


def reject_plan(session: SessionState, notes: str = "") -> SessionState:
    record_approval(session, "reject", notes=notes)
    return session
