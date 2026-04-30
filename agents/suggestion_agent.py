"""
Agent 2 – Suggestion / Planning Agent
=======================================
Takes RequirementAnalysis and produces a SuggestionPlan.
Human-in-the-loop gate: schema generation is blocked until plan is approved.
RAG context enriches suggestions.
"""
from __future__ import annotations
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from models import (
    RequirementAnalysis, SuggestionPlan, Entity, Attribute,
    Relationship, SuggestedFeature,
)
from services.llm_service import get_chat_llm

logger = logging.getLogger(__name__)

_SYSTEM = """You are a senior database architect creating a design proposal.
Given a requirement analysis and similar schemas from a knowledge base,
produce a comprehensive but lean suggestion plan.

Return ONLY valid JSON (no markdown):
{{
  "suggested_entities": [
    {{
      "name": "table_name",
      "description": "what this entity represents",
      "attributes": [
        {{
          "name": "id",
          "data_type": "UUID",
          "is_primary_key": true,
          "is_foreign_key": false,
          "is_nullable": false,
          "is_unique": true,
          "references_table": null,
          "references_column": null,
          "description": "Primary key"
        }}
      ]
    }}
  ],
  "suggested_relationships": [
    {{
      "from_entity": "EntityA",
      "to_entity": "EntityB",
      "relationship_type": "one-to-many",
      "label": "has"
    }}
  ],
  "optional_features": [
    {{
      "name": "Audit Logging",
      "description": "Track all changes",
      "entities_involved": ["AuditLog"]
    }}
  ],
  "rationale": "Why these design decisions were made"
}}

Rules (ALWAYS apply):
0. Use only the requirement analysis provided. Do not invent facts, policies, or entities that are not implied by those inputs.
1. Every entity MUST have an id UUID primary key.
2. Every foreign key MUST be explicit in attributes.
3. Normalise to 3NF.
4. Use precise SQL data types.
5. Junction tables required for every many-to-many relationship.
6. If the requirement analysis includes relationships, reuse them in the plan.
7. Every suggested entity should participate in at least one relationship unless it is clearly an isolated lookup/reference table.
8. Add NOT NULL where semantically required.
9. Use snake_case for all names.
10. If inputs are missing or unclear, choose the smallest conservative schema and state the uncertainty in rationale.

CRITICAL: Return valid JSON. Each entity MUST appear in suggested_entities.
STRICTLY FORBIDDEN to use SQL reserved words for entity or attribute names.
Do not rely on quoting. Use descriptive alternatives (e.g., user_account, order_record, group_name, leave_table).
"""

_HUMAN = """Requirement Analysis:
{analysis_json}

RAG Context (similar schemas):
{rag_context}

Produce the suggestion plan now."""


def _parse_analysis_relationships(
    analysis: RequirementAnalysis,
    valid_entities: set[str],
) -> list[Relationship]:
    relationships: list[Relationship] = []
    for rel in (analysis.relationships if isinstance(analysis.relationships, list) else []):
        if not isinstance(rel, dict):
            continue
        try:
            relationship = Relationship(
                from_entity=rel.get("from") or rel.get("from_entity"),
                to_entity=rel.get("to") or rel.get("to_entity"),
                relationship_type=rel.get("type") or rel.get("relationship_type"),
                label=rel.get("label"),
            )
            if relationship.from_entity in valid_entities and relationship.to_entity in valid_entities:
                relationships.append(relationship)
        except Exception as exc:
            logger.warning("Skipping invalid analysis relationship: %s", exc)
    return relationships


def _enforce_relationships(
    entities: list[Entity],
    relationships: list[Relationship],
    analysis: RequirementAnalysis,
) -> list[Relationship]:
    valid_names = {entity.name for entity in entities}
    filtered: list[Relationship] = []
    for rel in relationships:
        if rel.from_entity in valid_names and rel.to_entity in valid_names and rel.from_entity != rel.to_entity:
            filtered.append(rel)
        else:
            logger.warning(
                "Ignoring relationship with invalid or missing table names: %s -> %s",
                getattr(rel, "from_entity", None),
                getattr(rel, "to_entity", None),
            )
    relationships = filtered

    if not relationships:
        relationships = _parse_analysis_relationships(analysis, valid_names)

    if not relationships and len(valid_names) > 1:
        names = list(valid_names)
        for i in range(len(names) - 1):
            relationships.append(Relationship(
                from_entity=names[i],
                to_entity=names[i + 1],
                relationship_type="one-to-many",
                label="related to",
            ))
        logger.info("Added fallback relationships connecting suggested entities.")

    return relationships


def _ensure_primary_key(entity: Entity) -> Entity:
    if not any(attr.is_primary_key for attr in entity.attributes):
        entity.attributes.insert(0, Attribute(
            name="id", data_type="UUID",
            is_primary_key=True, is_nullable=False,
            description="Primary key",
        ))
    return entity


def run_suggestion_agent(
    analysis: RequirementAnalysis,
    rag_context: str = "",
) -> SuggestionPlan:
    llm = get_chat_llm(temperature=0.0)
    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    chain = prompt | llm | JsonOutputParser()

    logger.info("Running Suggestion Agent…")
    raw = chain.invoke({
        "analysis_json": analysis.model_dump_json(indent=2),
        "rag_context": rag_context or "No similar schemas available.",
    })

    # Safe extraction
    entities_raw = raw.get("suggested_entities", [])
    if not isinstance(entities_raw, list):
        entities_raw = []

    entities = []
    for e in entities_raw:
        try:
            entity = Entity(**e)
            entities.append(_ensure_primary_key(entity))
        except Exception as exc:
            logger.warning("Skipping invalid entity: %s", exc)

    relationships_raw = raw.get("suggested_relationships", [])
    relationships = []
    for r in (relationships_raw if isinstance(relationships_raw, list) else []):
        try:
            relationships.append(Relationship(**r))
        except Exception as exc:
            logger.warning("Skipping invalid relationship: %s", exc)

    relationships = _enforce_relationships(entities, relationships, analysis)

    features_raw = raw.get("optional_features", [])
    features = []
    for feature_payload in (features_raw if isinstance(features_raw, list) else []):
        try:
            features.append(SuggestedFeature(**feature_payload))
        except Exception as exc:
            logger.warning("Skipping invalid feature: %s", exc)

    # Fallback: derive from analysis if LLM returned nothing
    if not entities:
        logger.warning("No entities from LLM — falling back to analysis entities.")
        for name in analysis.entities:
            entities.append(Entity(
                name=name,
                attributes=[Attribute(
                    name="id", data_type="UUID",
                    is_primary_key=True, is_nullable=False,
                )],
            ))

    return SuggestionPlan(
        suggested_entities=entities,
        suggested_relationships=relationships,
        optional_features=features,
        rationale=raw.get("rationale"),
        rag_references=[rag_context] if rag_context else [],
    )


_MODIFY_SYSTEM = """You are a senior database architect. Update the existing suggestion plan to reflect the user's modification request.
Return ONLY valid JSON matching the SuggestionPlan schema. Preserve unchanged entities, relationships, and features.
Use only the existing plan, original requirement analysis, and modification instruction. Do not invent unrelated entities, relationships, features, or business rules.
If the user asks to add or remove entities, reflect that in suggested_entities. If they ask to modify relationships, update suggested_relationships accordingly.
If the user asks to add optional features, keep existing optional_features and append the new ones instead of replacing them.
If the user requests optional features, also add any supporting entities and relationships required so the ERD can reflect those features.
Ensure the final modified plan includes at least one relationship between entities whenever more than one entity exists.
If the modification is missing or unclear, preserve the existing plan and explain the uncertainty in rationale.
Do not include narrative text outside the JSON response.
STRICTLY FORBIDDEN to use SQL reserved words for entity or attribute names.
Do not rely on quoting. Use descriptive alternatives (e.g., user_account, order_record, group_name, leave_table).
"""

_MODIFY_HUMAN = """Existing suggestion plan:
{plan_json}

Original requirement analysis:
{analysis_json}

Apply this modification instruction exactly:
{modification_instruction}
"""


def _merge_optional_features(
    existing_features: list[SuggestedFeature],
    modified_features: list[SuggestedFeature],
) -> list[SuggestedFeature]:
    """Preserve existing optional features while appending new ones."""
    merged = {feature.name.lower(): feature for feature in existing_features}
    for feature in modified_features:
        key = feature.name.lower()
        merged[key] = feature
    return list(merged.values())


def run_plan_modifier(
    existing_plan: SuggestionPlan,
    modification_instruction: str,
    analysis: RequirementAnalysis,
) -> SuggestionPlan:
    llm = get_chat_llm(temperature=0.0)
    prompt = ChatPromptTemplate.from_messages([
        ("system", _MODIFY_SYSTEM),
        ("human", _MODIFY_HUMAN),
    ])
    chain = prompt | llm | JsonOutputParser()

    logger.info("Running Plan Modifier…")
    try:
        raw = chain.invoke({
            "plan_json": existing_plan.model_dump_json(indent=2),
            "analysis_json": analysis.model_dump_json(indent=2),
            "modification_instruction": modification_instruction,
        })
    except Exception as exc:
        logger.error("Plan modifier failed: %s", exc)
        raw = {}

    entities_raw = raw.get("suggested_entities", [])
    if not isinstance(entities_raw, list):
        entities_raw = [e.model_dump() for e in existing_plan.suggested_entities]

    entities = []
    for e in entities_raw:
        try:
            entity = Entity(**e)
            entities.append(_ensure_primary_key(entity))
        except Exception as exc:
            logger.warning("Skipping invalid modified entity: %s", exc)

    relationships_raw = raw.get("suggested_relationships", [])
    relationships = []
    for r in (relationships_raw if isinstance(relationships_raw, list) else []):
        try:
            relationships.append(Relationship(**r))
        except Exception as exc:
            logger.warning("Skipping invalid modified relationship: %s", exc)

    relationships = _enforce_relationships(entities, relationships, analysis) if entities else existing_plan.suggested_relationships
    if not relationships and len(entities) > 1:
        relationships = _enforce_relationships(entities, [], analysis)
        logger.info("Adding fallback relationships after modification to preserve entity connectivity.")

    features_raw = raw.get("optional_features", [])
    modified_features = []
    for feature_payload in (features_raw if isinstance(features_raw, list) else []):
        try:
            modified_features.append(SuggestedFeature(**feature_payload))
        except Exception as exc:
            logger.warning("Skipping invalid modified feature: %s", exc)

    if not entities:
        logger.warning("Plan modifier returned no entities, preserving existing plan.")
        entities = existing_plan.suggested_entities

    if modified_features:
        optional_features = _merge_optional_features(
            existing_plan.optional_features,
            modified_features,
        )
    else:
        optional_features = existing_plan.optional_features
        if any(k in modification_instruction.lower() for k in ["optional feature", "optional features"]):
            fallback_feature = SuggestedFeature(
                name="Additional Optional Features",
                description=(
                    "User requested extra optional features. "
                    "These can be refined once an LLM response is available."
                ),
                entities_involved=[entity.name for entity in entities[:3]],
            )
            optional_features = existing_plan.optional_features + [fallback_feature]
            logger.info("Applied fallback optional feature due to modification instruction.")

    return SuggestionPlan(
        suggested_entities=entities,
        suggested_relationships=relationships or existing_plan.suggested_relationships,
        optional_features=optional_features,
        rationale=raw.get("rationale") or existing_plan.rationale,
        rag_references=existing_plan.rag_references + [modification_instruction],
    )
