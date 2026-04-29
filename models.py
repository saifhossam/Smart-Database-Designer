"""
Core Pydantic models shared across the DB Designer Agent system.
"""
from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


# ─────────────────────────────────────────────
# Domain Models
# ─────────────────────────────────────────────

class Attribute(BaseModel):
    name: str
    data_type: str
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_nullable: bool = True
    is_unique: bool = False
    references_table: Optional[str] = None
    references_column: Optional[str] = None
    description: Optional[str] = None
    default_value: Optional[str] = None


class Entity(BaseModel):
    name: str
    description: Optional[str] = None
    attributes: List[Attribute] = Field(default_factory=list)


class Relationship(BaseModel):
    from_entity: str
    to_entity: str
    relationship_type: Literal["one-to-one", "one-to-many", "many-to-many", "many-to-one"]
    label: Optional[str] = None
    through_table: Optional[str] = None


class SuggestedFeature(BaseModel):
    name: str
    description: str
    entities_involved: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Agent Output Models
# ─────────────────────────────────────────────

class RequirementAnalysis(BaseModel):
    """Output of the Requirement Analyzer Agent."""
    raw_input: str
    entities: List[str]
    attributes: Dict[str, List[str]]
    relationships: List[Dict[str, str]]
    domain: Optional[str] = None
    analysis_notes: Optional[str] = None


class SuggestionPlan(BaseModel):
    """Output of the Suggestion / Planning Agent (pre-approval)."""
    suggested_entities: List[Entity]
    suggested_relationships: List[Relationship]
    optional_features: List[SuggestedFeature]
    rationale: Optional[str] = None
    rag_references: List[str] = Field(default_factory=list)


class ApprovalRecord(BaseModel):
    """Tracks a single human-in-the-loop approval event."""
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    decision: Literal["approved", "rejected"]
    plan_snapshot: SuggestionPlan
    notes: Optional[str] = None


class ColumnDefinition(BaseModel):
    name: str
    data_type: str
    constraints: List[str] = Field(default_factory=list)
    references: Optional[str] = None
    description: Optional[str] = None


class TableDefinition(BaseModel):
    name: str
    columns: List[ColumnDefinition]
    indexes: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class DatabaseSchema(BaseModel):
    """Full normalised schema produced by the Schema Designer Agent."""
    tables: List[TableDefinition]
    relationships: List[Relationship]
    normalization_level: str = "3NF"
    version: int = 1
    fix_log: List[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    category: Literal["CRITICAL", "FIXABLE", "INFO"] = Field(default="CRITICAL")
    table: Optional[str] = None
    column: Optional[str] = None
    message: str
    suggestion: Optional[str] = None


class ValidationResult(BaseModel):
    """Output of the Validation Agent."""
    is_valid: bool
    status: Literal["clean", "fixed", "warning"] = "warning"
    validity: Literal["valid", "needs_improvement", "invalid"] = "needs_improvement"
    issues: List[ValidationIssue] = Field(default_factory=list)
    issues_detected: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[ValidationIssue] = Field(default_factory=list)
    auto_fixes: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning: List[str] = Field(default_factory=list)
    alternative_designs: List[Dict[str, Any]] = Field(default_factory=list)
    final_schema: Optional[Dict[str, Any]] = None
    corrected_schema: Optional[DatabaseSchema] = None
    resolved_issues: List[str] = Field(default_factory=list)
    rule_based_fixes: List[str] = Field(default_factory=list)
    rule_based_issues: List[ValidationIssue] = Field(default_factory=list)
    llm_suggestions: List[ValidationIssue] = Field(default_factory=list)
    critical_issues: List[str] = Field(default_factory=list)
    final_corrected_schema: Optional[Dict[str, Any]] = None


class QuerySet(BaseModel):
    """Output of the Query Generator Agent."""
    crud_queries: Dict[str, List[str]]
    analytical_queries: List[Dict[str, str]]


# ─────────────────────────────────────────────
# Session / Memory Models
# ─────────────────────────────────────────────

class SessionState(BaseModel):
    """Full state for one design session (persisted in memory layer)."""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    user_input: str = ""
    requirement_analysis: Optional[RequirementAnalysis] = None
    suggestion_plan: Optional[SuggestionPlan] = None
    approval_record: Optional[ApprovalRecord] = None
    database_schema: Optional[DatabaseSchema] = None
    validation_result: Optional[ValidationResult] = None
    query_set: Optional[QuerySet] = None
    final_report: Optional[Dict[str, Any]] = None
    db_file_path: Optional[str] = None
    sql_schema: Optional[str] = None
    modification_history: List[str] = Field(default_factory=list)
    iteration: int = 1
    status: Literal[
        "init", "analyzing", "suggesting", "awaiting_approval",
        "approved", "rejected", "designing", "validating",
        "generating_queries", "complete",
    ] = "init"
    messages: List[Dict[str, Any]] = Field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({
            "role": role,
            "content": content,
            "ts": datetime.utcnow().isoformat(),
        })