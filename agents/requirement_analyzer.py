"""
Agent 1 – Requirement Analyzer
================================
Parses natural-language input into structured entities, attributes,
and preliminary relationships using LLM + structured output.
"""
from __future__ import annotations
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from models import RequirementAnalysis
from services.llm_service import get_chat_llm

logger = logging.getLogger(__name__)

_SYSTEM = """You are a senior database architect specialising in requirements analysis.
Extract structured database design information from the user's natural-language description.
The user input may be in English, Arabic, or a mixture of both.

Return ONLY valid JSON matching this schema (no markdown fences):
{{
  "entities": ["EntityName", ...],
  "attributes": {{
    "EntityName": ["attribute1", "attribute2", ...]
  }},
  "relationships": [
    {{"from": "EntityA", "to": "EntityB", "type": "one-to-many", "label": "has"}}
  ],
  "domain": "e-commerce | healthcare | education | ...",
  "analysis_notes": "brief explanation of your reasoning"
}}

Rules:
- Identify ALL implied entities, even if not explicitly named.
- Every entity MUST have an id attribute.
- Relationships must specify type: one-to-one | one-to-many | many-to-many.
- Resolve ambiguities conservatively.
- Relations must be between entities.
- Avoid SQL Reserved Keywords: Never use SQL reserved keywords (e.g., TABLE, USER, ORDER, GROUP, SELECT, FROM) as entity names. If the user implies such a name, append a context-specific suffix (e.g., use dining_table instead of table, app_user instead of user).

CRITICAL: Return JSON only.
"""

_HUMAN = "Analyze this database requirement:\n\n{user_input}"


def run_requirement_analyzer(user_input: str) -> RequirementAnalysis:
    llm = get_chat_llm(temperature=0.0)
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    chain = prompt | llm | JsonOutputParser()

    logger.info("Running Requirement Analyzer…")
    try:
        raw = chain.invoke({"user_input": user_input})
    except Exception as exc:
        logger.error("Requirement analyzer failed: %s", exc)
        raw = {
            "entities": ["User", "Data"],
            "attributes": {"User": ["id", "name"], "Data": ["id", "content"]},
            "relationships": [],
            "domain": "generic",
            "analysis_notes": "Fallback analysis due to LLM error",
        }

    entities = raw.get("entities", []) if isinstance(raw.get("entities"), list) else []
    attributes = raw.get("attributes", {}) if isinstance(raw.get("attributes"), dict) else {}
    relationships = raw.get("relationships", []) if isinstance(raw.get("relationships"), list) else []

    return RequirementAnalysis(
        raw_input=user_input,
        entities=entities,
        attributes=attributes,
        relationships=relationships,
        domain=raw.get("domain"),
        analysis_notes=raw.get("analysis_notes"),
    )