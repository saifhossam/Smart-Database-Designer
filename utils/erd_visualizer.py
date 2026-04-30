"""
ERD Visualizer
===============
Generates interactive HTML ERD diagrams (using Pyvis) and SQL DDL.
Falls back gracefully if pyvis is not installed.
"""
from __future__ import annotations
import logging
import re
import sqlite3
from pathlib import Path

from models import DatabaseSchema, SuggestionPlan

logger = logging.getLogger(__name__)

# Colour palette
_COLOURS = [
    "#4fc3f7", "#81c784", "#ffb74d", "#f06292",
    "#ce93d8", "#80cbc4", "#fff176", "#ff8a65",
]


# ─────────────────────────────────────────────────────────────────────────────
# SQL DDL Generator
# ─────────────────────────────────────────────────────────────────────────────

def _quote_identifier(name: str) -> str:
    if not name:
        return name
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def _get_primary_key_columns(table) -> list[str]:
    return [
        col.name
        for col in table.columns
        if any("PRIMARY KEY" in c.upper() for c in col.constraints)
    ]


def _quote_reference(reference: str) -> str:
    if not reference:
        return reference
    parts = reference.strip().split("(", 1)
    if len(parts) != 2:
        return reference
    table_name = parts[0].strip()
    rest = parts[1].rstrip(") ")
    column_name = rest.strip()
    return f"{_quote_identifier(table_name)}({_quote_identifier(column_name)})"


def _format_column_definition(col, remove_pk: bool = False, sqlite: bool = False) -> str:
    constraints = []
    for c in col.constraints:
        if remove_pk and "PRIMARY KEY" in c.upper():
            continue
        constraints.append(c)

    if sqlite:
        constraints = [
            _normalize_default(c) if c.strip().upper().startswith("DEFAULT") else c
            for c in constraints
        ]

    constraints_str = " ".join(constraints).strip()
    col_type = _normalize_sqlite_type(col.data_type) if sqlite else col.data_type
    col_def = f"    {_quote_identifier(col.name)} {col_type}"
    if constraints_str:
        col_def += f" {constraints_str}"
    if col.references:
        col_def += f" REFERENCES {_quote_reference(col.references)}"
    return col_def


def _normalize_sqlite_type(data_type: str) -> str:
    dt = data_type.strip().upper()
    if "UUID" in dt:
        return "TEXT"
    if "TIMESTAMP" in dt:
        return "TEXT"
    if "SERIAL" in dt or "BIGSERIAL" in dt:
        return "INTEGER"
    if dt.startswith("VARCHAR") or dt.startswith("CHAR"):
        return dt
    return dt


def _normalize_default(default: str) -> str:
    if not default:
        return ""
    if "gen_random_uuid" in default.lower():
        return "DEFAULT (lower(hex(randomblob(16))))"
    if "now()" in default.lower():
        return "DEFAULT CURRENT_TIMESTAMP"
    return default


def generate_sqlite_ddl(schema: DatabaseSchema) -> str:
    """Generate a SQLite-compatible DDL script from a DatabaseSchema."""
    if not schema or not schema.tables:
        return "-- No tables defined"

    lines = [
        "-- ============================================================",
        "-- Auto-generated SQLite schema by DB Designer Agent",
        f"-- Normalization: {schema.normalization_level}",
        "-- ============================================================",
        "",
        "PRAGMA foreign_keys = ON;",
        "BEGIN TRANSACTION;",
        "",
    ]

    for table in schema.tables:
        lines.append(f"-- {table.description or table.name}")
        lines.append(f"CREATE TABLE IF NOT EXISTS {_quote_identifier(table.name)} (")

        pk_columns = _get_primary_key_columns(table)
        use_table_pk = len(pk_columns) > 1

        col_lines = [
            _format_column_definition(col, remove_pk=use_table_pk, sqlite=True)
            for col in table.columns
        ]

        if use_table_pk:
            quoted_pk = ", ".join(_quote_identifier(col) for col in pk_columns)
            col_lines.append(f"    PRIMARY KEY ({quoted_pk})")

        # FIX: Proper closing parenthesis on same line
        lines.append(",\n".join(col_lines))
        lines.append(");\n")

        for idx in table.indexes:
            lines.append(idx + ";")
        
        lines.append("")

    lines += ["COMMIT;", ""]
    return "\n".join(lines)

def create_sqlite_database(schema: DatabaseSchema, project_name: str, output_dir: str = "output") -> tuple[str, str]:
    """Create a SQLite .db file from a schema and return (path, ddl)."""
    if not schema or not schema.tables:
        raise ValueError("No schema available to generate SQLite database.")

    safe_name = re.sub(r"[^0-9a-zA-Z_]+", "_", project_name.strip().lower() or "db_design").strip("_")
    safe_name = (safe_name[:32] or "db_design").strip("_")
    if not safe_name:
        safe_name = "db_design"

    db_dir = Path(output_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / f"{safe_name}.db"
    if db_path.exists():
        db_path.unlink()

    ddl = generate_sqlite_ddl(schema)
    
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.executescript(ddl)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"SQLite error: {e}\n\nDDL:\n{ddl}")
        conn.close()
        if db_path.exists():
            db_path.unlink()
        raise RuntimeError(f"SQLite database creation failed: {e}") from e
    finally:
        conn.close()

    return str(db_path.resolve()), ddl


# ─────────────────────────────────────────────────────────────────────────────
# ERD from SuggestionPlan (pre-approval view)
# ─────────────────────────────────────────────────────────────────────────────

def build_erd_html_from_plan(plan: SuggestionPlan) -> str:
    """Build an interactive ERD HTML string from a SuggestionPlan."""
    if not plan or not plan.suggested_entities:
        return "<p>No entities to display.</p>"

    try:
        from pyvis.network import Network
        return _pyvis_from_plan(plan)
    except ImportError:
        logger.warning("pyvis not installed — returning static HTML ERD.")
        return _static_html_from_plan(plan)


def _pyvis_from_plan(plan: SuggestionPlan) -> str:
    from pyvis.network import Network

    net = Network(height="500px", width="100%", bgcolor="#0d1b2a", font_color="#e0f4ff")
    net.set_options("""{
      "nodes": {"shape": "box", "margin": 10, "font": {"size": 13}},
      "edges": {"arrows": {"to": {"enabled": true}}, "color": {"color": "#4fc3f7"}},
      "physics": {"forceAtlas2Based": {"gravitationalConstant": -50}, "solver": "forceAtlas2Based"}
    }""")

    for i, entity in enumerate(plan.suggested_entities):
        colour = _COLOURS[i % len(_COLOURS)]
        label = f"{entity.name}\n" + "\n".join(
            f"  {'🔑 ' if a.is_primary_key else '🔗 ' if a.is_foreign_key else '• '}{a.name}: {a.data_type}"
            for a in entity.attributes[:6]
        )
        if len(entity.attributes) > 6:
            label += f"\n  … +{len(entity.attributes)-6} more"
        net.add_node(entity.name, label=label, color=colour, title=entity.description or "")

    for rel in plan.suggested_relationships:
        label = {"one-to-one": "1:1", "one-to-many": "1:N", "many-to-many": "N:M"}.get(
            rel.relationship_type, rel.relationship_type
        )
        net.add_edge(rel.from_entity, rel.to_entity, label=label, title=rel.label or "")

    return net.generate_html()


def _static_html_from_plan(plan: SuggestionPlan) -> str:
    """Minimal static ERD for when pyvis is unavailable."""
    rows = ""
    for i, entity in enumerate(plan.suggested_entities):
        colour = _COLOURS[i % len(_COLOURS)]
        attrs = "".join(
            f"<tr><td style='padding:2px 8px;color:#ccc'>"
            f"{'🔑' if a.is_primary_key else '🔗' if a.is_foreign_key else '•'} "
            f"{a.name}</td><td style='color:#4fc3f7;padding:2px 8px'>{a.data_type}</td></tr>"
            for a in entity.attributes
        )
        rows += f"""
        <div style='display:inline-block;margin:10px;vertical-align:top;
                    background:#0d1b2a;border:2px solid {colour};border-radius:8px;min-width:180px'>
          <div style='background:{colour};color:#000;padding:6px 12px;font-weight:700'>{entity.name}</div>
          <table style='border-collapse:collapse;width:100%'>{attrs}</table>
        </div>"""
    return f"<div style='font-family:monospace;overflow:auto'>{rows}</div>"


# ─────────────────────────────────────────────────────────────────────────────
# ERD from DatabaseSchema (post-approval view)
# ─────────────────────────────────────────────────────────────────────────────

def build_erd_html_from_schema(schema: DatabaseSchema) -> str:
    """Build an interactive ERD HTML string from a DatabaseSchema."""
    if not schema or not schema.tables:
        return "<p>No tables to display.</p>"

    try:
        from pyvis.network import Network
        return _pyvis_from_schema(schema)
    except ImportError:
        logger.warning("pyvis not installed — returning static HTML ERD.")
        return _static_html_from_schema(schema)


def _pyvis_from_schema(schema: DatabaseSchema) -> str:
    from pyvis.network import Network

    net = Network(height="550px", width="100%", bgcolor="#0d1b2a", font_color="#e0f4ff")
    net.set_options("""{
      "nodes": {"shape": "box", "margin": 10, "font": {"size": 12}},
      "edges": {"arrows": {"to": {"enabled": true}}, "color": {"color": "#4fc3f7"}},
      "physics": {"forceAtlas2Based": {"gravitationalConstant": -60}, "solver": "forceAtlas2Based"}
    }""")

    for i, table in enumerate(schema.tables):
        colour = _COLOURS[i % len(_COLOURS)]
        label = f"{table.name}\n" + "\n".join(
            f"  {'🔑 ' if 'PRIMARY KEY' in c.constraints else '🔗 ' if c.references else '• '}"
            f"{c.name}: {c.data_type}"
            for c in table.columns[:7]
        )
        if len(table.columns) > 7:
            label += f"\n  … +{len(table.columns)-7} more"
        net.add_node(table.name, label=label, color=colour, title=table.description or "")

    for rel in schema.relationships:
        label = {"one-to-one": "1:1", "one-to-many": "1:N", "many-to-many": "N:M"}.get(
            rel.relationship_type, ""
        )
        try:
            net.add_edge(rel.from_entity, rel.to_entity, label=label)
        except Exception:
            pass  # skip edges for missing nodes

    return net.generate_html()


def _static_html_from_schema(schema: DatabaseSchema) -> str:
    rows = ""
    for i, table in enumerate(schema.tables):
        colour = _COLOURS[i % len(_COLOURS)]
        cols_html = "".join(
            f"<tr><td style='padding:2px 8px;color:#ccc'>"
            f"{'🔑' if 'PRIMARY KEY' in c.constraints else '🔗' if c.references else '•'} "
            f"{c.name}</td><td style='color:#4fc3f7;padding:2px 8px'>{c.data_type}</td>"
            f"<td style='color:#888;padding:2px 8px;font-size:0.8em'>"
            f"{', '.join(c.constraints[:2])}</td></tr>"
            for c in table.columns
        )
        rows += f"""
        <div style='display:inline-block;margin:10px;vertical-align:top;
                    background:#0d1b2a;border:2px solid {colour};border-radius:8px;min-width:220px'>
          <div style='background:{colour};color:#000;padding:6px 12px;font-weight:700'>{table.name}</div>
          <table style='border-collapse:collapse;width:100%'>{cols_html}</table>
        </div>"""
    return f"<div style='font-family:monospace;overflow:auto'>{rows}</div>"
