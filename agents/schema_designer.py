"""
Agent 3 – Schema Designer
==========================
Converts an APPROVED SuggestionPlan into a fully normalised DatabaseSchema.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from models import SuggestionPlan, DatabaseSchema, TableDefinition, Relationship
from services.llm_service import get_chat_llm
from validators import production_validation

logger = logging.getLogger(__name__)

GLOBAL_RULES = """You are a secure, deterministic database design agent.

GLOBAL SAFETY & INTEGRITY RULES — NEVER VIOLATE THESE: [same as above]"""

_SYSTEM = """{{GLOBAL_RULES}}

ROLE: Schema Designer
Convert an APPROVED SuggestionPlan into a complete, normalized DatabaseSchema.

INPUT: Approved SuggestionPlan

RULES:
- Include EVERY entity from the plan as a table.
- For every relationship, create corresponding FOREIGN KEY in the child table.
- Every table must have id UUID PRIMARY KEY.
- Add created_at / updated_at where appropriate.
- Generate useful indexes.
- Maintain 3NF normalization.

OUTPUT FORMAT — Return ONLY this JSON:
{{
  "tables": [{{TableDefinition with columns and indexes}}],
  "relationships": [{{Relationship}}],
  "normalization_level": "3NF"
}}
"""

_HUMAN = "Approved Suggestion Plan:\n\n{plan_json}\n\nGenerate the complete production-ready schema."


def run_schema_designer(plan: SuggestionPlan) -> DatabaseSchema:
    from .validation_agent import run_validation_agent 
    
    llm = get_chat_llm(temperature=0.0)
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    chain = prompt | llm | JsonOutputParser()

    logger.info("Running Schema Designer…")
    raw = chain.invoke({"plan_json": plan.model_dump_json(indent=2)})

    tables_raw = raw.get("tables", []) if isinstance(raw.get("tables"), list) else []
    relationships_raw = raw.get("relationships", []) if isinstance(raw.get("relationships"), list) else []

    tables = []
    for t in tables_raw:
        if "columns" in t:
            for col in t["columns"]:
                ref = col.get("references")
                if isinstance(ref, dict):
                    table_name = ref.get("table") or ref.get("table_name")
                    col_name = ref.get("column") or ref.get("column_name")
                    col["references"] = f"{table_name}({col_name})" if table_name and col_name else table_name
        try:
            tables.append(TableDefinition(**t))
        except Exception as exc:
            logger.warning("Skipping invalid table: %s", exc)

    relationships = [Relationship(**r) for r in relationships_raw if isinstance(r, dict)]

    schema = DatabaseSchema(
        tables=tables,
        relationships=relationships,
        normalization_level=raw.get("normalization_level", "3NF"),
    )

    validation_result = run_validation_agent(schema)

    if validation_result.corrected_schema:
        schema = validation_result.corrected_schema
        schema.__dict__["fix_log"] = validation_result.resolved_issues or []
    else:
        schema.__dict__["fix_log"] = []

    schema, report = production_validation(plan, schema)
    return schema