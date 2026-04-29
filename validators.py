"""
Comprehensive Validation & Recovery Layer
==========================================
Ensures:
  1. Every suggested entity becomes a table
  2. No relationships reference non-existent tables
  3. Schema completeness is verified at each stage
  4. Incomplete LLM outputs are recovered / repaired
  5. Deterministic naming consistency throughout
"""
from __future__ import annotations
import re
import logging
from typing import List, Dict, Tuple, Any

from models import (
    Entity, Relationship, SuggestionPlan, DatabaseSchema,
    TableDefinition, ColumnDefinition, Attribute, ValidationIssue,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Naming helpers
# ─────────────────────────────────────────────────────────────────────────────

def normalize_naming(name: str) -> str:
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    name = name.lower()
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def standardize_entity_names(entities: List[Entity]) -> List[Entity]:
    for entity in entities:
        entity.name = normalize_naming(entity.name)
        for attr in entity.attributes:
            attr.name = normalize_naming(attr.name)
    return entities


def standardize_relationship_names(relationships: List[Relationship]) -> List[Relationship]:
    for rel in relationships:
        rel.from_entity = normalize_naming(rel.from_entity)
        rel.to_entity = normalize_naming(rel.to_entity)
    return relationships


def standardize_table_names(schema: DatabaseSchema) -> DatabaseSchema:
    for table in schema.tables:
        table.name = normalize_naming(table.name)
        for col in table.columns:
            col.name = normalize_naming(col.name)
            if col.references:
                parts = col.references.split("(")
                if len(parts) == 2:
                    col.references = f"{normalize_naming(parts[0])}({parts[1]}"
    for rel in schema.relationships:
        rel.from_entity = normalize_naming(rel.from_entity)
        rel.to_entity = normalize_naming(rel.to_entity)
    return schema


def _normalize_column_type(column: ColumnDefinition) -> str:
    original = column.data_type.strip()
    normalized = original.upper()
    if normalized in {"STRING", "STR"}:
        column.data_type = "TEXT"
        return f"Converted nonstandard type {original} to TEXT on {column.name}."
    if normalized == "INT":
        column.data_type = "INTEGER"
        return f"Converted nonstandard type INT to INTEGER on {column.name}."
    if normalized == "DATETIME":
        column.data_type = "TIMESTAMP"
        return f"Converted DATETIME to TIMESTAMP on {column.name}."
    return ""


_TYPE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\s+[A-Za-z_][A-Za-z0-9_]*)*(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?$")

def _is_plausible_sql_type(data_type: str) -> bool:
    return bool(_TYPE_PATTERN.match(data_type.strip()))


# ─────────────────────────────────────────────────────────────────────────────
# Core Validation 
# ─────────────────────────────────────────────────────────────────────────────

def rule_based_validation(
    schema: DatabaseSchema,
) -> Tuple[DatabaseSchema, List[ValidationIssue], List[str], List[Dict[str, Any]]]:

    issues: List[ValidationIssue] = []
    fix_log: List[str] = []
    fix_actions: List[Dict[str, Any]] = []

    table_map = {t.name: t for t in schema.tables}

    # duplicate tables
    normalized_table_counts: Dict[str, int] = {}
    for table in schema.tables:
        normalized_name = normalize_naming(table.name)
        normalized_table_counts[normalized_name] = normalized_table_counts.get(normalized_name, 0) + 1

    for table_name, count in normalized_table_counts.items():
        if count > 1:
            issues.append(ValidationIssue(
                severity="warning",
                table=table_name,
                message=f"Duplicate table name '{table_name}' detected.",
                suggestion="Keep table names unique.",
            ))

    # columns validation
    for table in schema.tables:
        seen: set[str] = set()
        unique_columns: List[ColumnDefinition] = []

        for col in table.columns:
            normalized_name = normalize_naming(col.name)

            if normalized_name in seen:
                fix_log.append(f"Removed duplicate column '{col.name}' from table '{table.name}'.")
                fix_actions.append({
                    "type": "duplicate_column",
                    "table": table.name,
                    "column": col.name,
                })
                continue

            seen.add(normalized_name)
            unique_columns.append(col)

        table.columns = unique_columns

        # ensure PK
        if not any("PRIMARY KEY" in c.constraints for c in table.columns):
            table.columns.insert(0, ColumnDefinition(
                name="id",
                data_type="UUID",
                constraints=["PRIMARY KEY", "NOT NULL", "DEFAULT gen_random_uuid()"],
                description="Auto-generated primary key",
            ))
            fix_log.append(f"Created missing PRIMARY KEY on table '{table.name}'.")

        # column checks
        for column in table.columns:
            type_fix = _normalize_column_type(column)
            if type_fix:
                fix_log.append(type_fix)
            elif column.data_type.strip() and not _is_plausible_sql_type(column.data_type):
                issues.append(ValidationIssue(
                    severity="warning",
                    table=table.name,
                    column=column.name,
                    message=f"Unusual SQL type '{column.data_type}' used.",
                ))

            # FK validation
            if column.references:
                target = column.references.split("(")[0].strip()
                if target and target not in table_map:
                    issues.append(ValidationIssue(
                        severity="warning",
                        table=table.name,
                        column=column.name,
                        message=f"Foreign key reference '{column.references}' invalid.",
                    ))
                    column.references = None
                    fix_log.append(f"Removed invalid FK from '{table.name}.{column.name}'.")

    # relationships validation
    valid_relationships: List[Relationship] = []
    for rel in schema.relationships:
        if rel.from_entity not in table_map or rel.to_entity not in table_map:
            issues.append(ValidationIssue(
                severity="warning",
                message=f"Invalid relationship {rel.from_entity} → {rel.to_entity}.",
            ))
            fix_log.append(f"Removed invalid relationship '{rel.from_entity} → {rel.to_entity}'.")
        else:
            valid_relationships.append(rel)

    schema.relationships = valid_relationships

    return schema, issues, fix_log, fix_actions


# ─────────────────────────────────────────────────────────────────────────────
# Recovery
# ─────────────────────────────────────────────────────────────────────────────

def _entity_attrs_to_columns(entity: Entity) -> List[ColumnDefinition]:
    columns: List[ColumnDefinition] = []

    for attr in entity.attributes:
        constraints: List[str] = []

        if attr.is_primary_key:
            constraints += ["PRIMARY KEY", "NOT NULL"]
            if attr.data_type == "UUID":
                constraints.append("DEFAULT gen_random_uuid()")
        elif not attr.is_nullable:
            constraints.append("NOT NULL")

        if attr.is_unique and not attr.is_primary_key:
            constraints.append("UNIQUE")

        references = None
        if attr.is_foreign_key and attr.references_table:
            references = f"{normalize_naming(attr.references_table)}({attr.references_column or 'id'})"

        columns.append(ColumnDefinition(
            name=attr.name,
            data_type=attr.data_type,
            constraints=constraints,
            references=references,
            description=attr.description,
        ))

    if not any("PRIMARY KEY" in c.constraints for c in columns):
        columns.insert(0, ColumnDefinition(
            name="id",
            data_type="UUID",
            constraints=["PRIMARY KEY", "NOT NULL", "DEFAULT gen_random_uuid()"],
            description="Auto-generated primary key",
        ))

    return columns


def recover_missing_tables(plan: SuggestionPlan, schema: DatabaseSchema) -> DatabaseSchema:
    schema_names = {t.name for t in schema.tables}

    for entity in plan.suggested_entities:
        if entity.name not in schema_names:
            logger.warning("Reconstructing missing table: %s", entity.name)
            schema.tables.append(TableDefinition(
                name=entity.name,
                columns=_entity_attrs_to_columns(entity),
                description=entity.description,
            ))

    return schema


# ─────────────────────────────────────────────────────────────────────────────
# Production validation
# ─────────────────────────────────────────────────────────────────────────────

def production_validation(
    plan: SuggestionPlan,
    schema: DatabaseSchema,
) -> Tuple[DatabaseSchema, Dict[str, Any]]:

    logger.info("Running production validation…")

    plan.suggested_entities = standardize_entity_names(plan.suggested_entities)
    plan.suggested_relationships = standardize_relationship_names(plan.suggested_relationships)
    schema = standardize_table_names(schema)

    schema = recover_missing_tables(plan, schema)

    # New sync step
    schema = sync_relationships_and_foreign_keys(plan, schema)

    schema, removed_rels = validate_and_repair_relationships(schema)

    fix_log = getattr(schema, 'fix_log', []) + removed_rels
    schema.fix_log = fix_log

    return schema, {
        "fix_log": fix_log,
        "removed_relationships": removed_rels,
    }

def sync_relationships_and_foreign_keys(
    plan: SuggestionPlan, 
    schema: DatabaseSchema
) -> DatabaseSchema:
    """Ensure all relationships from plan exist in schema and create missing FK columns."""
    logger.info("Syncing relationships and foreign keys from SuggestionPlan...")

    table_map = {t.name: t for t in schema.tables}
    existing_rel_set = {(r.from_entity, r.to_entity) for r in schema.relationships}

    for rel in plan.suggested_relationships:
        from_name = normalize_naming(rel.from_entity)
        to_name = normalize_naming(rel.to_entity)

        if from_name not in table_map or to_name not in table_map:
            continue

        rel_key = (from_name, to_name)
        if rel_key in existing_rel_set or (to_name, from_name) in existing_rel_set:
            continue  # already exists

        # Add the relationship
        schema.relationships.append(Relationship(
            from_entity=from_name,
            to_entity=to_name,
            relationship_type=rel.relationship_type,
            label=rel.label,
        ))

        # Add FK column in the "many" side (simple heuristic)
        child_table = table_map.get(to_name) if rel.relationship_type in ("one-to-many", "many-to-one") else None
        if not child_table and rel.relationship_type == "many-to-many":
            # For many-to-many we expect junction table already created by LLM
            continue

        if child_table and from_name not in [c.name for c in child_table.columns]:
            fk_col_name = f"{from_name}_id"
            child_table.columns.append(ColumnDefinition(
                name=fk_col_name,
                data_type="UUID",
                constraints=["NOT NULL"],
                references=f"{from_name}(id)",
                description=f"Foreign key to {from_name}",
            ))
            logger.info(f"Added missing FK column {fk_col_name} in table {to_name}")

    return schema

def validate_and_repair_relationships(
    schema: DatabaseSchema,
) -> Tuple[DatabaseSchema, List[str]]:
    table_names = {t.name for t in schema.tables}
    valid, removed = [], []

    for rel in schema.relationships:
        if rel.from_entity not in table_names or rel.to_entity not in table_names:
            msg = f"Removed invalid relationship: {rel.from_entity} → {rel.to_entity}"
            logger.warning(msg)
            removed.append(msg)
        else:
            valid.append(rel)

    schema.relationships = valid
    return schema, removed