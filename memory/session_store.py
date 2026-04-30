"""
Memory / Context Layer
=======================
Manages session state persistence using JSON files.
"""
from __future__ import annotations
import json
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional

from models import SessionState, ApprovalRecord

logger = logging.getLogger(__name__)

_STORE_DIR = Path(os.getenv("MEMORY_DIR", "/tmp/db_designer_sessions"))
_STORE_DIR.mkdir(parents=True, exist_ok=True)

_cache: Dict[str, SessionState] = {}


def save_session(state: SessionState) -> None:
    _cache[state.session_id] = state
    path = _STORE_DIR / f"{state.session_id}.json"
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    logger.debug("Session %s saved.", state.session_id)


def load_session(session_id: str) -> Optional[SessionState]:
    if session_id in _cache:
        return _cache[session_id]
    path = _STORE_DIR / f"{session_id}.json"
    if path.exists():
        state = SessionState.model_validate_json(path.read_text(encoding="utf-8"))
        _cache[session_id] = state
        return state
    return None


def list_sessions() -> List[Dict]:
    summaries = []
    for path in sorted(_STORE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            summaries.append({
                "session_id": data["session_id"],
                "created_at": data.get("created_at", ""),
                "status": data.get("status", "unknown"),
                "user_input": data.get("user_input", "")[:80],
                "iteration": data.get("iteration", 1),
            })
        except Exception:
            pass
    return summaries


def clear_sessions() -> None:
    """Delete all saved session files and clear the in-memory cache."""
    _cache.clear()
    for path in _STORE_DIR.glob("*.json"):
        try:
            path.unlink()
        except Exception as exc:
            logger.warning("Could not delete session file %s: %s", path, exc)


def record_approval(state: SessionState, decision: str, notes: str = "") -> ApprovalRecord:
    if state.suggestion_plan is None:
        raise ValueError("No suggestion plan to record approval for.")
    record = ApprovalRecord(
        session_id=state.session_id,
        decision="approved" if decision == "approve" else "rejected",
        plan_snapshot=state.suggestion_plan,
        notes=notes,
    )
    state.approval_record = record
    state.status = "approved" if record.decision == "approved" else "rejected"
    state.add_message("system", f"Human decision: {record.decision}")
    save_session(state)
    return record


def get_recent_schemas(limit: int = 5) -> List[str]:
    results = []
    for summary in list_sessions()[:limit]:
        session = load_session(summary["session_id"])
        if session and session.database_schema:
            results.append(session.database_schema.model_dump_json())
    return results
