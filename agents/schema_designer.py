"""
Agent 3 – Schema Designer (Fixed & Strengthened)
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from models import SuggestionPlan, DatabaseSchema, TableDefinition, Relationship
from services.llm_service import get_chat_llm
from validators import production_validation, recover_missing_tables

logger = logging.getLogger(__name__)

_SYSTEM = """You are a senior database engineer converting a design plan into a production-ready schema.

Return ONLY valid JSON (no markdown, no extra text):
{{
  "tables": [ ... ],
  "relationships": [ ... ],
  "normalization_level": "3NF"
}}

CRITICAL RULES (must follow strictly):

1. Include EVERY entity from the suggestion plan as a table.
2. Every table MUST have: 
   - "id" UUID PRIMARY KEY with DEFAULT gen_random_uuid()
   - created_at TIMESTAMP NOT NULL DEFAULT NOW()
3. For EVERY relationship in the plan:
   - If one-to-many or many-to-one → Add FK column in the "many" side.
   - If many-to-many → Create explicit junction table (with two FKs).
   - Always set the "references" field correctly as "parent_table(id)".
4. Use snake_case only.
5. Never use SQL reserved keywords as table/column names.
6. Make sure all FK columns exist in the child tables.

Compare the output with the input plan carefully before responding."""

_HUMAN = """Approved Suggestion Plan:
{plan_json}

Generate the complete production-ready normalized schema now."""


def run_schema_designer(plan: SuggestionPlan) -> DatabaseSchema:
    llm = get_chat_llm(temperature=0.0)
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    chain = prompt | llm | JsonOutputParser()

    logger.info("Running Schema Designer Agent…")
    raw = chain.invoke({"plan_json": plan.model_dump_json(indent=2)})

    # Parse tables
    tables_raw = raw.get("tables", []) if isinstance(raw.get("tables"), list) else []
    tables = []
    for t in tables_raw:
        try:
            # Fix references if returned as dict
            for col in t.get("columns", []):
                if isinstance(col.get("references"), dict):
                    tbl = col["references"].get("table") or col["references"].get("table_name")
                    col_name = col["references"].get("column") or "id"
                    col["references"] = f"{tbl}({col_name})" if tbl else None
            tables.append(TableDefinition(**t))
        except Exception as exc:
            logger.warning("Skipping invalid table from LLM: %s", exc)

    # Parse relationships
    relationships_raw = raw.get("relationships", []) if isinstance(raw.get("relationships"), list) else []
    relationships = []
    for r in relationships_raw:
        try:
            relationships.append(Relationship(**r))
        except Exception as exc:
            logger.warning("Skipping invalid relationship: %s", exc)

    schema = DatabaseSchema(
        tables=tables,
        relationships=relationships,
        normalization_level=raw.get("normalization_level", "3NF"),
    )

    logger.info(f"Schema Designer returned {len(schema.tables)} tables and {len(schema.relationships)} relationships")

    # === Recovery & Sync Step ===
    schema = recover_missing_tables(plan, schema)                    # recover missing tables
    schema, _ = production_validation(plan, schema)                  # standardize + repair

    logger.info(f"After recovery & production validation → {len(schema.tables)} tables, {len(schema.relationships)} relationships")

    return schema