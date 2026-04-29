"""
Agent 4 – Validation Agent
============================
Validates the DatabaseSchema for structural integrity and best practices.

Report filtering:
  - Only surfaces CRITICAL errors and IMPORTANT warnings.
  - Removes repetitive / low-value noise (e.g. ENUM vs VARCHAR debates).
"""
from __future__ import annotations
import logging
import re
from typing import Any, Dict, List, Optional, Set

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from models import (
    DatabaseSchema, ValidationResult, ValidationIssue,
    TableDefinition, ColumnDefinition, Relationship,
)
from services.llm_service import get_chat_llm
from validators import standardize_table_names, rule_based_validation

logger = logging.getLogger(__name__)

# ─── Noise patterns to suppress ───────────────────────────────────────────────
# These are low-value, repetitive suggestions that clutter the report.

_SUPPRESS_PATTERNS: List[str] = [
    "enum",
    "consider using enum",
    "varchar vs",
    "vs varchar",
    "text vs varchar",
    "unbounded text",
    "consider adding",
    "you might want",
    "could be improved",
    "for better performance consider",
    "n+1",           # too speculative without context
    "scalability risk",
]


def _is_noise(issue: ValidationIssue) -> bool:
    """Return True if the issue is low-value noise that should be filtered out."""
    msg_lower = issue.message.lower()
    sug_lower = (issue.suggestion or "").lower()
    combined = msg_lower + " " + sug_lower
    return any(pat in combined for pat in _SUPPRESS_PATTERNS)


def _classify_issue(issue: ValidationIssue) -> str:
    """Classify issues into CRITICAL, FIXABLE, and INFO categories."""
    if issue.severity == "error":
        return "CRITICAL"
    if issue.severity == "warning":
        return "FIXABLE"
    return "INFO"


def _build_issue_detail(issue: ValidationIssue, fix_actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    location = issue.table or "schema"
    if issue.column:
        location = f"{location}.{issue.column}"
    issue_type = "validation"
    if "duplicate column" in issue.message.lower():
        issue_type = "duplicate_column"
    elif "foreign key" in issue.message.lower() or "references" in issue.message.lower():
        issue_type = "foreign_key"
    elif "duplicate table" in issue.message.lower():
        issue_type = "duplicate_table"
    elif "reserved keyword" in issue.message.lower():
        issue_type = "reserved_keyword"
    elif "unsupported sql type" in issue.message.lower() or "sql type" in issue.message.lower():
        issue_type = "data_type"
    elif "relationship" in issue.message.lower():
        issue_type = "relationship"

    action = issue.suggestion or "review the design"
    detail: Dict[str, Any] = {
        "type": issue_type,
        "location": location,
        "issue": issue.message,
        "action": action,
    }
    for fix in fix_actions:
        if fix.get("table") == issue.table and fix.get("column") == issue.column:
            detail["action"] = fix.get("action")
            if fix.get("original") is not None:
                detail["original"] = fix.get("original")
            if fix.get("fixed_to") is not None:
                detail["fixed_to"] = fix.get("fixed_to")
            if fix.get("status") is not None:
                detail["status"] = fix.get("status")
            break
        if fix.get("table") == issue.table and fix.get("column") is None and issue_type == fix.get("type"):
            detail["action"] = fix.get("action")
            if fix.get("original") is not None:
                detail["original"] = fix.get("original")
            if fix.get("fixed_to") is not None:
                detail["fixed_to"] = fix.get("fixed_to")
            if fix.get("status") is not None:
                detail["status"] = fix.get("status")
            break

    return detail


# ─── LLM deep validation ──────────────────────────────────────────────────────
def _llm_dynamic_validation(
    schema: DatabaseSchema,
    domain: str = "unknown",
) -> tuple[
    List[ValidationIssue],
    List[ValidationIssue],
    Optional[DatabaseSchema],
    List[str],
    List[Dict[str, Any]],
]:
    """Run the LLM-based semantic validation layer and return issues, suggestions, reasoning, alternatives, and any corrected schema."""
    llm_issues: List[ValidationIssue] = []
    suggestions: List[ValidationIssue] = []
    corrected_schema: Optional[DatabaseSchema] = None

    llm = get_chat_llm(temperature=0.0)
    prompt = ChatPromptTemplate.from_messages([
        ("system", _LLM_SYSTEM),
        ("human", _LLM_HUMAN),
    ])
    chain = prompt | llm | JsonOutputParser()

    logger.info("Running dynamic LLM validation…")
    try:
        raw = chain.invoke({
            "schema_json": schema.model_dump_json(indent=2),
            "domain": domain,
        })
    except Exception as exc:
        logger.error("LLM validation failed: %s", exc)
        raw = {
            "issues": [],
            "suggestions": [],
            "reasoning": [],
            "alternative_designs": [],
            "corrected_tables": [],
        }

    llm_issues_raw = raw.get("issues", []) if isinstance(raw.get("issues"), list) else []
    for item in llm_issues_raw:
        try:
            llm_issues.append(ValidationIssue(**item))
        except Exception as exc:
            logger.warning("Skipping invalid LLM issue: %s", exc)

    suggestions_raw = raw.get("suggestions", []) if isinstance(raw.get("suggestions"), list) else []
    for item in suggestions_raw:
        try:
            suggestions.append(ValidationIssue(**item))
        except Exception as exc:
            logger.warning("Skipping invalid LLM suggestion: %s", exc)

    reasoning_raw = raw.get("reasoning", []) if isinstance(raw.get("reasoning"), list) else []
    alternative_raw = raw.get("alternative_designs", []) if isinstance(raw.get("alternative_designs"), list) else []

    corrected_raw = raw.get("corrected_tables", []) if isinstance(raw.get("corrected_tables"), list) else []
    if corrected_raw:
        try:
            corrected_tables = [TableDefinition(**t) for t in corrected_raw if isinstance(t, dict)]
            if corrected_tables:
                corrected_schema = DatabaseSchema(
                    tables=corrected_tables,
                    relationships=schema.relationships,
                    normalization_level=schema.normalization_level,
                    version=schema.version + 1,
                )
        except Exception as exc:
            logger.warning("Could not parse corrected_tables from LLM: %s", exc)

    return llm_issues, suggestions, corrected_schema, reasoning_raw, alternative_raw


# ─── LLM deep validation ──────────────────────────────────────────────────────

_LLM_SYSTEM = """You are a senior database architect reviewing a schema.
Analyze the submitted design in the context of the inferred domain.
Focus on whether the model is logically consistent, structurally complete, and appropriate for the business context.
Do not hardcode domain-specific tables or force audit patterns unless clearly justified by the schema and domain.
Prefer guidance over enforcement.

Always return ONLY valid JSON with no markdown.

The response MUST include:
{{
  "issues": [
    {{
      "severity": "error|warning|info",
      "table": "table_name or null",
      "column": "column_name or null",
      "message": "concise description of the issue",
      "suggestion": "specific fix"
    }}
  ],
  "suggestions": [
    {{
      "severity": "error|warning|info",
      "table": "table_name or null",
      "column": "column_name or null",
      "message": "specific recommendation",
      "suggestion": "what to change"
    }}
  ],
  "reasoning": ["explain why this design choice matters"],
  "alternative_designs": [
    {{
      "description": "alternative design idea",
      "details": "how it would change the schema"
    }}
  ],
  "corrected_tables": []
}}

For every suggestion, explain the reasoning and offer alternative ways to achieve the same goal.
Do not invent unrelated business rules or force extra columns unless they are clearly supported by the domain.
Keyword Collision Check: Identify any table or column names that are SQL reserved keywords. If found, mark them as CRITICAL errors and provide a corrected name in corrected_tables.
"""

_LLM_HUMAN = "Review this schema in domain context:\n\nDomain: {domain}\n\n{schema_json}"


def run_validation_agent(schema: DatabaseSchema, domain: str = "unknown") -> ValidationResult:
    """Validate schema with a hybrid rule-based and LLM validation pipeline."""
    rule_schema, rule_issues, rule_fixes, fix_actions = rule_based_validation(schema)
    llm_issues, llm_suggestions, llm_corrected_schema, llm_reasoning, llm_alternatives = _llm_dynamic_validation(
        rule_schema,
        domain=domain,
    )

    final_schema = llm_corrected_schema or rule_schema
    merged_issues: List[ValidationIssue] = []
    seen: Set[str] = set()
    for issue in rule_issues + llm_issues:
        key = f"{issue.severity}:{issue.table}:{issue.message[:60]}"
        if key not in seen:
            seen.add(key)
            merged_issues.append(issue)

    for issue in merged_issues:
        issue.category = _classify_issue(issue)

    critical_issues = [
        issue.message for issue in merged_issues
        if issue.severity == "error" or issue.category == "CRITICAL"
    ]

    final_corrected_schema = final_schema.model_dump() if final_schema else None
    is_valid = not any(issue.severity == "error" for issue in merged_issues)
    validity = "valid" if is_valid and not any(issue.severity == "warning" for issue in merged_issues) else (
        "invalid" if any(issue.severity == "error" for issue in merged_issues) else "needs_improvement"
    )
    issue_details = [
        _build_issue_detail(issue, fix_actions)
        for issue in merged_issues
    ]
    status = "fixed" if fix_actions else ("warning" if issue_details else "clean")

    return ValidationResult(
        is_valid=is_valid,
        status=status,
        validity=validity,
        issues=[issue for issue in merged_issues if issue.severity != "info" or issue.category != "INFO"],
        issues_detected=issue_details,
        suggestions=llm_suggestions,
        auto_fixes=fix_actions,
        reasoning=llm_reasoning,
        alternative_designs=llm_alternatives,
        final_schema=final_corrected_schema,
        corrected_schema=final_schema,
        resolved_issues=rule_fixes,
        rule_based_fixes=rule_fixes,
        rule_based_issues=rule_issues,
        llm_suggestions=llm_suggestions,
        critical_issues=critical_issues,
        final_corrected_schema=final_corrected_schema,
    )