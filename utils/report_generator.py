"""
Final Report Generator (Updated with Fix Reporting)
===================================================
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from models import (
    RequirementAnalysis, SuggestionPlan,
    DatabaseSchema, QuerySet, ValidationResult,
)

def generate_final_report(
    session_id: str,
    user_input: str,
    requirement_analysis: Optional[RequirementAnalysis],
    suggestion_plan: Optional[SuggestionPlan],
    schema: Optional[DatabaseSchema],
    validation_result: Optional[ValidationResult],
    query_set: Optional[QuerySet],
) -> Dict[str, Any]:
    
    total_tables = len(schema.tables) if schema else 0
    total_columns = sum(len(t.columns) for t in schema.tables) if schema else 0
    
    applied_fixes = getattr(schema, 'fix_log', []) or []
    validation_fixes = validation_result.resolved_issues if validation_result else []
    resolved_issues = applied_fixes + [item for item in validation_fixes if item not in applied_fixes]

    planned_entities = ({e.name for e in suggestion_plan.suggested_entities} if suggestion_plan else set())
    actual_tables = {t.name for t in schema.tables} if schema else set()
    missing = list(planned_entities - actual_tables)

    validation_details = {
        "status": validation_result.status if validation_result else "warning",
        "validity": validation_result.validity if validation_result else "unknown",
        "is_complete": len(missing) == 0,
        "missing_tables": missing,
        "resolved_issues": resolved_issues,
        "resolved_count": len(resolved_issues),
        "auto_fixes": validation_result.auto_fixes if validation_result else [],
        "issues_detected": validation_result.issues_detected if validation_result else [],
        "rule_based_fixes": validation_result.rule_based_fixes if validation_result else [],
        "rule_based_issues": [issue.model_dump() for issue in validation_result.rule_based_issues] if validation_result else [],
        "suggestions": [issue.model_dump() for issue in validation_result.suggestions] if validation_result else [],
        "reasoning": validation_result.reasoning if validation_result else [],
        "alternative_designs": validation_result.alternative_designs if validation_result else [],
        "llm_suggestions": [issue.model_dump() for issue in validation_result.llm_suggestions] if validation_result else [],
        "critical_issues": validation_result.critical_issues if validation_result else [],
        "final_schema": validation_result.final_schema if validation_result else None,
        "final_corrected_schema": validation_result.final_corrected_schema if validation_result else None,
        "resolved_message": (
            "Validation warnings/errors were resolved." if resolved_issues else "No validation issues were present."
        ),
    }

    report = {
        "session_id": session_id,
        "statistics": {
            "total_tables": total_tables,
            "total_columns": total_columns,
            "normalization_level": schema.normalization_level if schema else "N/A",
        },
        "auto_recovery": {
            "status": "Fixed & Optimized" if resolved_issues else "Healthy",
            "applied_fixes": resolved_issues,
            "message": (
                "The system detected validation issues and automatically resolved them before showing results." 
                if resolved_issues else "No validation warnings or errors were detected."
            ),
        },
        "validation": validation_details,
        "domain": requirement_analysis.domain if requirement_analysis else "unknown",
    }
    return report
