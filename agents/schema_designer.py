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

_SYSTEM = """You are a senior database engineer converting a design plan into a production-ready schema.

Return ONLY valid JSON (no markdown):
{{
  "tables": [
    {{
      "name": "table_name",
      "description": "what this table stores",
      "columns": [
        {{
          "name": "id",
          "data_type": "UUID",
          "constraints": ["PRIMARY KEY", "NOT NULL", "DEFAULT gen_random_uuid()"],
          "references": null,
          "description": "Primary key"
        }}
      ],
      "indexes": ["CREATE INDEX idx_table_col ON table_name(col)"]
    }}
  ],
  "relationships": [
    {{
      "from_entity": "TableA",
      "to_entity": "TableB",
      "relationship_type": "one-to-many",
      "label": "has"
    }}
  ],
  "normalization_level": "3NF"
}}

Rules:
1. Every table MUST have an id UUID PRIMARY KEY.
2. CRITICAL: For every relationship defined in the plan, you MUST create a corresponding Foreign Key column in the child table.
3. All FK columns MUST have the 'references' property set to 'parent_table(id)'.
4. Use snake_case for all names.
5. Include created_at TIMESTAMP NOT NULL DEFAULT NOW() on every table with > 2 columns.

DOUBEL-CHECK: Compare your 'tables' columns against the 'relationships' list to ensure no connection is missing.
CRITICAL: Include ALL entities from the plan. Do not drop any.
Avoid using SQL reserved keywords for table or column names. If a name like table is requested, rename it to [entity]_table.
"""

_HUMAN = """Approved Suggestion Plan:
{plan_json}

Generate the complete production-ready schema for ALL entities above."""


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