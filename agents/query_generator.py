"""
Agent 5 – Query Generator
==========================
Generates CRUD and analytical SQL queries for every table in the schema.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from models import DatabaseSchema, QuerySet
from services.llm_service import get_chat_llm

logger = logging.getLogger(__name__)

_SYSTEM = """You are an expert SQL engineer. Generate comprehensive SQL queries for the given schema.

Output format:
{{
  "crud_queries": {{
    "table_name": [
      "INSERT INTO table_name (...) VALUES (...)",
      "SELECT * FROM table_name WHERE id = $1",
      "UPDATE table_name SET ... WHERE id = $1",
      "DELETE FROM table_name WHERE id = $1"
    ]
  }},
  "analytical_queries": [
    {{
      "name": "query_name",
      "description": "what this query answers",
      "sql": "SELECT ... FROM ... JOIN ... WHERE ..."
    }}
  ]
}}

Rules:
- Each table MUST have exactly 4 queries: INSERT, SELECT, UPDATE, DELETE (as a list of strings).
- Analytical queries should JOIN across tables and answer business questions.
- Use PostgreSQL syntax ($1, $2 placeholders).
- Add SQL comments on complex queries.

CRITICAL: Return valid JSON. crud_queries values must be arrays of strings (NOT objects).
"""

_HUMAN = "Generate CRUD and analytical queries for:\n\n{schema_json}"


def _normalize_crud(raw_crud: Dict[str, Any]) -> Dict[str, List[str]]:
    """Normalise crud_queries values — LLM sometimes returns dicts instead of lists."""
    normalized: Dict[str, List[str]] = {}
    for table, ops in raw_crud.items():
        if isinstance(ops, dict):
            normalized[table] = list(ops.values())
        elif isinstance(ops, list):
            normalized[table] = [str(q) for q in ops]
        else:
            normalized[table] = []
    return normalized


def run_query_generator(schema: DatabaseSchema) -> QuerySet:
    llm = get_chat_llm(temperature=0.0)
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    chain = prompt | llm | JsonOutputParser()

    logger.info("Running Query Generator…")
    raw = chain.invoke({"schema_json": schema.model_dump_json(indent=2)})

    crud_raw = raw.get("crud_queries", {}) if isinstance(raw.get("crud_queries"), dict) else {}
    analytical_raw = raw.get("analytical_queries", []) if isinstance(raw.get("analytical_queries"), list) else []

    fixed_crud = _normalize_crud(crud_raw)

    # Stub fallback for any table the LLM missed
    for table in schema.tables:
        if table.name not in fixed_crud or len(fixed_crud[table.name]) < 4:
            logger.warning("Generating stub queries for table '%s'.", table.name)
            pk_col = next(
                (c.name for c in table.columns if "PRIMARY KEY" in c.constraints), "id"
            )
            table_name = '"{}"'.format(table.name.replace('"', '""'))
            pk_col_quoted = '"{}"'.format(pk_col.replace('"', '""'))
            fixed_crud[table.name] = [
                f"INSERT INTO {table_name} DEFAULT VALUES;",
                f"SELECT * FROM {table_name} WHERE {pk_col_quoted} = $1;",
                f"UPDATE {table_name} SET updated_at = NOW() WHERE {pk_col_quoted} = $1;",
                f"DELETE FROM {table_name} WHERE {pk_col_quoted} = $1;",
            ]

    return QuerySet(crud_queries=fixed_crud, analytical_queries=analytical_raw)