"""Introspect a PostgreSQL schema into a structure consumable by LLM prompts.

Pulls table/column metadata and comments from pg_catalog, single-column
foreign keys from pg_constraint, and (optionally) text-match joins from a
YAML file at a caller-provided path. Low-cardinality VARCHAR/TEXT columns
are sampled for enum-like values.

Three sources of truth, each in the right place:
  1. types, FKs, primary keys           — pg_catalog (auto-current)
  2. business descriptions              — COMMENT ON TABLE/COLUMN (lives with data)
  3. text-match joins (semantic, not FK) — relationships.yaml (git-reviewable)

Usage:
    pool = await asyncpg.create_pool(...)
    ctx = await introspect_schema(
        pool,
        schemas=["bankdw", "salesforce"],
        text_joins_path="platform/db/relationships.yaml",
    )
    markdown = format_for_prompt(ctx)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import asyncpg
import yaml


# Maximum distinct values allowed before a column is no longer treated as enum-like.
ENUM_CARDINALITY_THRESHOLD = 25

# Base data types that are candidates for enum-value sampling.
_ENUM_BASE_TYPES = {"character varying", "text", "varchar"}

# Substrings (case-insensitive) in a column name that signal it is NOT an enum.
# Used to skip the per-column DISTINCT probe on free-text and identifier columns.
_ENUM_SKIP_PATTERNS = (
    "id", "key", "number", "date", "time", "name", "description",
    "subject", "email", "phone", "website", "address", "street",
    "comment", "note", "step", "secret", "swiftbic", "routingnumber",
    "postalcode", "taxid", "amount", "value",
)


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    description: Optional[str]
    enum_values: Optional[list[str]] = None


@dataclass(frozen=True)
class TableInfo:
    schema: str
    name: str
    description: Optional[str]
    columns: list[ColumnInfo]
    primary_key: list[str]


@dataclass(frozen=True)
class ForeignKey:
    from_schema: str
    from_table: str
    from_column: str
    to_schema: str
    to_table: str
    to_column: str


@dataclass(frozen=True)
class TextJoin:
    from_schema: str
    from_table: str
    from_column: str
    to_schema: str
    to_table: str
    to_column: str
    semantics: str


@dataclass(frozen=True)
class EntityPerspective:
    """One analytical angle into the data warehouse.

    Commercial-banking analysts ask questions from at least three
    perspectives — the *party* (corporate counterparty), the *bank*
    (financial institution facilitating the payment), and the *product*
    (payment rail like Wire/ACH/RTP). Surfacing these in the prompt
    makes the LLM's tool-routing decisions structural rather than
    rule-list-based.
    """
    name: str                       # e.g. "party", "bank", "product"
    description: str
    primary_table: str              # "schema.table"
    fact_columns: list[str]         # column(s) on the fact table that join here


@dataclass(frozen=True)
class SchemaContext:
    tables: list[TableInfo]
    foreign_keys: list[ForeignKey]
    text_joins: list[TextJoin]
    perspectives: list[EntityPerspective] = field(default_factory=list)


# ── Internal: heuristics ──────────────────────────────────────────────────

def _looks_like_enum_candidate(col_name: str, data_type: str) -> bool:
    """Pre-filter columns before running a DISTINCT probe.

    Returns False for non-string columns and for columns whose names suggest
    free-form text or identifiers — saves N round-trips at agent startup.
    """
    base = data_type.split("(", 1)[0].strip().lower()
    if base not in _ENUM_BASE_TYPES:
        return False
    lowered = col_name.lower()
    return not any(p in lowered for p in _ENUM_SKIP_PATTERNS)


def _qident(s: str) -> str:
    """Quote a SQL identifier — escape embedded double quotes."""
    return '"' + s.replace('"', '""') + '"'


# ── Internal: catalog queries ─────────────────────────────────────────────

async def _fetch_tables(
    conn: asyncpg.Connection, schemas: list[str]
) -> dict[tuple[str, str], Optional[str]]:
    rows = await conn.fetch(
        """
        SELECT
            n.nspname AS schema,
            c.relname AS table,
            obj_description(c.oid, 'pg_class') AS comment
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r'
          AND n.nspname = ANY($1::text[])
        ORDER BY n.nspname, c.relname
        """,
        schemas,
    )
    return {(r["schema"], r["table"]): r["comment"] for r in rows}


async def _fetch_columns(
    conn: asyncpg.Connection, schemas: list[str]
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT
            n.nspname AS schema,
            c.relname AS table,
            a.attname AS column,
            pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
            NOT a.attnotnull AS nullable,
            col_description(c.oid, a.attnum) AS comment,
            a.attnum AS ordinal
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE a.attnum > 0
          AND NOT a.attisdropped
          AND n.nspname = ANY($1::text[])
          AND c.relkind = 'r'
        ORDER BY n.nspname, c.relname, a.attnum
        """,
        schemas,
    )


async def _fetch_primary_keys(
    conn: asyncpg.Connection, schemas: list[str]
) -> dict[tuple[str, str], list[str]]:
    rows = await conn.fetch(
        """
        SELECT
            n.nspname AS schema,
            c.relname AS table,
            a.attname AS column,
            array_position(con.conkey, a.attnum) AS position
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(con.conkey)
        WHERE con.contype = 'p'
          AND n.nspname = ANY($1::text[])
        ORDER BY n.nspname, c.relname, position
        """,
        schemas,
    )
    out: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        out.setdefault((r["schema"], r["table"]), []).append(r["column"])
    return out


async def _fetch_foreign_keys(
    conn: asyncpg.Connection, schemas: list[str]
) -> list[ForeignKey]:
    """Fetch single-column foreign keys. Multi-column FKs are skipped."""
    rows = await conn.fetch(
        """
        SELECT
            n.nspname AS from_schema,
            c.relname AS from_table,
            a.attname AS from_column,
            fn.nspname AS to_schema,
            fc.relname AS to_table,
            fa.attname AS to_column
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_class fc ON fc.oid = con.confrelid
        JOIN pg_namespace fn ON fn.oid = fc.relnamespace
        JOIN pg_attribute a  ON a.attrelid  = c.oid  AND a.attnum  = con.conkey[1]
        JOIN pg_attribute fa ON fa.attrelid = fc.oid AND fa.attnum = con.confkey[1]
        WHERE con.contype = 'f'
          AND array_length(con.conkey, 1) = 1
          AND n.nspname = ANY($1::text[])
        ORDER BY n.nspname, c.relname, a.attname
        """,
        schemas,
    )
    return [
        ForeignKey(
            from_schema=r["from_schema"],
            from_table=r["from_table"],
            from_column=r["from_column"],
            to_schema=r["to_schema"],
            to_table=r["to_table"],
            to_column=r["to_column"],
        )
        for r in rows
    ]


async def _sample_enum_values(
    conn: asyncpg.Connection, schema: str, table: str, column: str
) -> Optional[list[str]]:
    """Return distinct values when the column has at most ENUM_CARDINALITY_THRESHOLD.

    Returns None when the cardinality exceeds the threshold (column is free-text)
    or when the probe fails for any reason — never raises.
    """
    sql = (
        f"SELECT {_qident(column)} AS v "
        f"FROM {_qident(schema)}.{_qident(table)} "
        f"WHERE {_qident(column)} IS NOT NULL "
        f"GROUP BY {_qident(column)} "
        f"ORDER BY {_qident(column)} "
        f"LIMIT {ENUM_CARDINALITY_THRESHOLD + 1}"
    )
    try:
        rows = await conn.fetch(sql)
    except Exception:
        return None
    if len(rows) > ENUM_CARDINALITY_THRESHOLD:
        return None
    return [str(r["v"]) for r in rows]


# ── YAML text-join loader ─────────────────────────────────────────────────

def _split_qualified(ident: str) -> tuple[str, str, str]:
    """Parse 'schema.table.column' allowing optional double quotes around parts."""
    parts = [p.strip().strip('"') for p in ident.split(".")]
    if len(parts) != 3:
        raise ValueError(f"expected schema.table.column, got {ident!r}")
    return parts[0], parts[1], parts[2]


def _load_relationships_yaml(
    path: Optional[Union[Path, str]],
) -> tuple[list[TextJoin], list[EntityPerspective]]:
    """Load text joins and analyst perspectives from a single YAML file.

    Both sections are optional. Missing file or missing sections degrade
    gracefully to empty lists so callers can ship partial data.
    """
    if path is None:
        return [], []
    p = Path(path)
    if not p.exists():
        return [], []
    raw = yaml.safe_load(p.read_text()) or {}

    joins: list[TextJoin] = []
    for item in raw.get("joins", []):
        from_schema, from_table, from_column = _split_qualified(item["from"])
        to_schema, to_table, to_column = _split_qualified(item["to"])
        joins.append(
            TextJoin(
                from_schema=from_schema,
                from_table=from_table,
                from_column=from_column,
                to_schema=to_schema,
                to_table=to_table,
                to_column=to_column,
                semantics=item.get("semantics", ""),
            )
        )

    perspectives: list[EntityPerspective] = []
    for item in raw.get("perspectives", []):
        perspectives.append(
            EntityPerspective(
                name=item["name"],
                description=item.get("description", ""),
                primary_table=item.get("primary_table", ""),
                fact_columns=list(item.get("fact_columns", [])),
            )
        )

    return joins, perspectives


# ── Public: introspect ────────────────────────────────────────────────────

async def introspect_schema(
    pool: asyncpg.Pool,
    schemas: list[str],
    *,
    relationships_path: Optional[Union[Path, str]] = None,
    sample_enums: bool = True,
) -> SchemaContext:
    """Build a SchemaContext from a live PostgreSQL connection.

    Args:
        pool: asyncpg pool connected to the target database.
        schemas: list of schema names to introspect (e.g. ["bankdw", "salesforce"]).
        relationships_path: path to a YAML file declaring text-match joins
            and analyst perspectives.
        sample_enums: when True, probes low-cardinality string columns for enum values.
    """
    async with pool.acquire() as conn:
        tables_meta = await _fetch_tables(conn, schemas)
        col_rows = await _fetch_columns(conn, schemas)
        pk_map = await _fetch_primary_keys(conn, schemas)
        fks = await _fetch_foreign_keys(conn, schemas)

        by_table: dict[tuple[str, str], list[asyncpg.Record]] = {}
        for r in col_rows:
            by_table.setdefault((r["schema"], r["table"]), []).append(r)

        tables: list[TableInfo] = []
        for (schema, table), col_records in by_table.items():
            column_infos: list[ColumnInfo] = []
            for r in col_records:
                col_name = r["column"]
                data_type = r["data_type"]
                enum_values: Optional[list[str]] = None
                if sample_enums and _looks_like_enum_candidate(col_name, data_type):
                    enum_values = await _sample_enum_values(conn, schema, table, col_name)
                column_infos.append(
                    ColumnInfo(
                        name=col_name,
                        data_type=data_type,
                        nullable=r["nullable"],
                        description=r["comment"],
                        enum_values=enum_values,
                    )
                )
            tables.append(
                TableInfo(
                    schema=schema,
                    name=table,
                    description=tables_meta.get((schema, table)),
                    columns=column_infos,
                    primary_key=pk_map.get((schema, table), []),
                )
            )

    text_joins, perspectives = _load_relationships_yaml(relationships_path)
    return SchemaContext(
        tables=tables,
        foreign_keys=fks,
        text_joins=text_joins,
        perspectives=perspectives,
    )


# ── Public: format for prompt ─────────────────────────────────────────────

def format_for_prompt(ctx: SchemaContext) -> str:
    """Render SchemaContext as Markdown ready to inject into a system prompt.

    Layout:
      ## Database Schema (live from pg_catalog)
      ### Schema: <name>
      #### <schema>."<table>"
        > <table description>
        PK: <cols>
        - "<col>" — <type> [— values: ...] [— <description>]
      ### Foreign Keys (declared)
      ### Text-Match Joins (semantic)
    """
    lines: list[str] = []

    if ctx.perspectives:
        lines.append("## Analyst Perspectives")
        lines.append("")
        lines.append(
            "Commercial-banking questions usually approach the data from one of "
            "these angles. Identify the perspective in the user's question, then "
            "filter on the matching column(s) on `bankdw.\"fact_payments\"`:"
        )
        lines.append("")
        for p in ctx.perspectives:
            cols = ", ".join(f'"{c}"' for c in p.fact_columns)
            lines.append(f"- **{p.name}** — {p.description}")
            if p.primary_table:
                lines.append(f"    primary table: `{p.primary_table}`")
            if cols:
                lines.append(f"    fact columns: {cols}")
        lines.append("")

    lines.append("## Database Schema (live from pg_catalog)")
    lines.append("")
    lines.append("Pascal-cased identifiers MUST be double-quoted in queries.")
    lines.append("")

    by_schema: dict[str, list[TableInfo]] = {}
    for t in ctx.tables:
        by_schema.setdefault(t.schema, []).append(t)

    for schema in sorted(by_schema.keys()):
        lines.append(f"### Schema: `{schema}`")
        lines.append("")
        for t in sorted(by_schema[schema], key=lambda x: x.name):
            full = f'{schema}."{t.name}"'
            lines.append(f"#### {full}")
            if t.description:
                lines.append(f"> {t.description}")
            if t.primary_key:
                lines.append(f"PK: {', '.join(t.primary_key)}")
            for c in t.columns:
                fragments = [f'"{c.name}"', c.data_type]
                line = "`" + "` `".join(fragments) + "`"
                if c.enum_values:
                    line += " — values: " + ", ".join(repr(v) for v in c.enum_values)
                if c.description:
                    line += f" — {c.description}"
                lines.append(f"- {line}")
            lines.append("")

    if ctx.foreign_keys:
        lines.append("### Foreign Keys (declared)")
        for fk in ctx.foreign_keys:
            lines.append(
                f'- {fk.from_schema}."{fk.from_table}"."{fk.from_column}" → '
                f'{fk.to_schema}."{fk.to_table}"."{fk.to_column}"'
            )
        lines.append("")

    if ctx.text_joins:
        lines.append("### Text-Match Joins (semantic, not enforced — match on equal values)")
        for tj in ctx.text_joins:
            line = (
                f'- {tj.from_schema}."{tj.from_table}"."{tj.from_column}" ↔ '
                f'{tj.to_schema}."{tj.to_table}"."{tj.to_column}"'
            )
            if tj.semantics:
                line += f" — {tj.semantics}"
            lines.append(line)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
