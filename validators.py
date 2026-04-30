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

_SQL_RESERVED_KEYWORDS = {
    "add", "all", "alter", "and", "as", "asc", "between", "by", "case", "check",
    "column", "constraint", "create", "delete", "desc", "distinct", "drop", "else",
    "exists", "foreign", "from", "group", "having", "in", "index", "insert", "into",
    "join", "key", "leave", "like", "limit", "not", "null", "or", "order",
    "primary", "references", "select", "set", "table", "then", "transaction",
    "union", "unique", "update", "user", "value", "values", "when", "where",
}

_RESERVED_RENAMES = {
    "group": "group_name",
    "index": "index_record",
    "leave": "leave_table",
    "order": "order_record",
    "table": "data_table",
    "user": "user_account",
    "value": "value_field",
}


# ─────────────────────────────────────────────────────────────────────────────
# Naming helpers
# ─────────────────────────────────────────────────────────────────────────────

def normalize_naming(name: str) -> str:
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    name = name.lower()
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def safe_sql_identifier(name: str, kind: str = "field") -> str:
    """Normalize an identifier and rename reserved SQL keywords without quoting."""
    normalized = normalize_naming(name)
    if normalized not in _SQL_RESERVED_KEYWORDS:
        return normalized
    if normalized in _RESERVED_RENAMES:
        return _RESERVED_RENAMES[normalized]
    suffix = "tbl" if kind == "table" else "col"
    return f"{normalized}_{suffix}"


def _rename_identifier(name: str, kind: str, fix_log: List[str], scope: str = "") -> str:
    safe_name = safe_sql_identifier(name, kind=kind)
    normalized = normalize_naming(name)
    if safe_name != normalized:
        location = f" in {scope}" if scope else ""
        fix_log.append(
            f"Renamed reserved SQL identifier '{normalized}' to '{safe_name}'{location}."
        )
    return safe_name


def _parse_reference(reference: str) -> Tuple[str, str] | None:
    parts = reference.strip().split("(", 1)
    if len(parts) != 2:
        return None
    table_name = parts[0].strip()
    column_name = parts[1].rstrip(") ").strip()
    if not table_name or not column_name:
        return None
    return table_name, column_name


def _format_reference(table_name: str, column_name: str) -> str:
    return f"{table_name}({column_name})"


def standardize_entity_names(entities: List[Entity]) -> List[Entity]:
    for entity in entities:
        entity.name = safe_sql_identifier(entity.name, kind="table")
        for attr in entity.attributes:
            attr.name = safe_sql_identifier(attr.name, kind="column")
            if attr.references_table:
                attr.references_table = safe_sql_identifier(attr.references_table, kind="table")
            if attr.references_column:
                attr.references_column = safe_sql_identifier(attr.references_column, kind="column")
    return entities


def standardize_relationship_names(relationships: List[Relationship]) -> List[Relationship]:
    for rel in relationships:
        rel.from_entity = safe_sql_identifier(rel.from_entity, kind="table")
        rel.to_entity = safe_sql_identifier(rel.to_entity, kind="table")
    return relationships


def standardize_table_names(schema: DatabaseSchema) -> DatabaseSchema:
    fix_log: List[str] = []
    table_renames: Dict[str, str] = {}
    column_renames: Dict[str, Dict[str, str]] = {}

    for table in schema.tables:
        original_table_name = normalize_naming(table.name)
        table.name = _rename_identifier(table.name, "table", fix_log)
        table_renames[original_table_name] = table.name
        column_renames.setdefault(table.name, {})

        for col in table.columns:
            original_column_name = normalize_naming(col.name)
            col.name = _rename_identifier(col.name, "column", fix_log, table.name)
            column_renames[table.name][original_column_name] = col.name

    for table in schema.tables:
        for col in table.columns:
            if not col.references:
                continue
            parsed = _parse_reference(col.references)
            if not parsed:
                continue
            ref_table, ref_column = parsed
            safe_ref_table = safe_sql_identifier(ref_table, kind="table")
            safe_ref_table = table_renames.get(normalize_naming(ref_table), safe_ref_table)
            safe_ref_column = safe_sql_identifier(ref_column, kind="column")
            safe_ref_column = column_renames.get(safe_ref_table, {}).get(
                normalize_naming(ref_column),
                safe_ref_column,
            )
            col.references = _format_reference(safe_ref_table, safe_ref_column)

    for rel in schema.relationships:
        from_name = safe_sql_identifier(rel.from_entity, kind="table")
        to_name = safe_sql_identifier(rel.to_entity, kind="table")
        rel.from_entity = table_renames.get(normalize_naming(rel.from_entity), from_name)
        rel.to_entity = table_renames.get(normalize_naming(rel.to_entity), to_name)

    if fix_log:
        schema.fix_log.extend(fix_log)
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

    schema = standardize_table_names(schema)
    issues: List[ValidationIssue] = []
    fix_log: List[str] = list(getattr(schema, "fix_log", []) or [])
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
            references = _format_reference(
                safe_sql_identifier(attr.references_table, kind="table"),
                safe_sql_identifier(attr.references_column or "id", kind="column"),
            )

        columns.append(ColumnDefinition(
            name=safe_sql_identifier(attr.name, kind="column"),
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
                name=safe_sql_identifier(entity.name, kind="table"),
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

    fix_log: List[str] = list(getattr(schema, "fix_log", []) or [])

    schema = recover_missing_tables(plan, schema)

    schema, removed_rels = validate_and_repair_relationships(schema)
    fix_log.extend(removed_rels)

    schema.fix_log = fix_log

    return schema, {
        "fix_log": fix_log,
        "removed_relationships": removed_rels,
    }


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
