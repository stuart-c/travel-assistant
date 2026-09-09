"""Database inspection and query execution tools for the MCP service."""

import logging
import re
from typing import Any, Dict, List, Optional

from app.db.core import db
from app.mcp.registry import register_tool
from app.mcp.server import get_cached_tool_permissions

logger = logging.getLogger(__name__)

# Permitted statement types in read_write mode
PERMITTED_MUTATING_STATEMENTS = ("INSERT", "UPDATE", "DELETE")


def _clean_sql(sql: str) -> str:
    """Strip block comments, line comments, and surrounding whitespace from SQL."""
    # Remove block comments /* ... */
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    # Remove single line comments -- ...
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql.strip()


def _has_multiple_statements(sql: str) -> bool:
    """Check if the SQL string contains multiple statements separated by semicolons."""
    in_single = False
    in_double = False
    statements: List[str] = []
    current: List[str] = []

    for char in sql:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == ";" and not in_single and not in_double:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            continue
        current.append(char)

    last = "".join(current).strip()
    if last:
        statements.append(last)

    return len(statements) > 1


def _extract_statement_type(cleaned_sql: str) -> str:
    """Determine the primary SQL command keyword (e.g. SELECT, INSERT, UPDATE, DELETE)."""
    tokens = re.findall(r"[A-Za-z]+", cleaned_sql)
    if not tokens:
        return "EMPTY"

    first = tokens[0].upper()
    if first == "WITH":
        # Check for subsequent command token in Common Table Expression
        for tok in tokens[1:]:
            up = tok.upper()
            if up in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                return up
        return "SELECT"

    return first


@register_tool(
    name="db_get_table_info",
    domain="database",
    description="Fetch database table names, schema definitions, column types, primary keys, and row counts.",
    is_mutating=False,
    allowed_levels=("disabled", "read"),
)
def db_get_table_info(
    table_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch schema, column definitions, indexes, and row counts for database tables."""
    try:
        if table_name:
            target_table = table_name.strip()
            if not re.match(r"^[A-Za-z0-9_]+$", target_table):
                return {
                    "success": False,
                    "error": f"Invalid table name format: '{target_table}'.",
                }

            cursor = db.execute_sql(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND name = ?",
                (target_table,),
            )
            row = cursor.fetchone()
            if not row:
                return {
                    "success": False,
                    "error": f"Table '{target_table}' does not exist in the database.",
                }

            sql_ddl = row[1]
            col_cursor = db.execute_sql(f'PRAGMA table_info("{target_table}")')
            columns = [
                {
                    "cid": col[0],
                    "name": col[1],
                    "type": col[2],
                    "notnull": bool(col[3]),
                    "default": col[4],
                    "primary_key": bool(col[5]),
                }
                for col in col_cursor.fetchall()
            ]

            idx_cursor = db.execute_sql(f'PRAGMA index_list("{target_table}")')
            indexes = [
                {
                    "seq": idx[0],
                    "name": idx[1],
                    "unique": bool(idx[2]),
                    "origin": idx[3],
                    "partial": bool(idx[4]),
                }
                for idx in idx_cursor.fetchall()
            ]

            fk_cursor = db.execute_sql(f'PRAGMA foreign_key_list("{target_table}")')
            foreign_keys = [
                {
                    "id": fk[0],
                    "seq": fk[1],
                    "table": fk[2],
                    "from": fk[3],
                    "to": fk[4],
                }
                for fk in fk_cursor.fetchall()
            ]

            count_cursor = db.execute_sql(f'SELECT count(*) FROM "{target_table}"')
            row_count = count_cursor.fetchone()[0]

            return {
                "success": True,
                "table": {
                    "name": target_table,
                    "row_count": row_count,
                    "columns": columns,
                    "indexes": indexes,
                    "foreign_keys": foreign_keys,
                    "sql": sql_ddl,
                },
            }

        # No table specified: list all application tables
        cursor = db.execute_sql(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        tables = []
        for name, sql_ddl in cursor.fetchall():
            col_cursor = db.execute_sql(f'PRAGMA table_info("{name}")')
            cols = [
                {
                    "cid": col[0],
                    "name": col[1],
                    "type": col[2],
                    "notnull": bool(col[3]),
                    "default": col[4],
                    "primary_key": bool(col[5]),
                }
                for col in col_cursor.fetchall()
            ]
            try:
                cnt_cursor = db.execute_sql(f'SELECT count(*) FROM "{name}"')
                row_cnt = cnt_cursor.fetchone()[0]
            except Exception:
                row_cnt = None

            tables.append(
                {
                    "name": name,
                    "row_count": row_cnt,
                    "columns": cols,
                    "sql": sql_ddl,
                }
            )

        return {
            "success": True,
            "table_count": len(tables),
            "tables": tables,
        }
    except Exception as err:
        logger.warning("Failed to fetch database table info: %s", err)
        return {
            "success": False,
            "error": f"Failed to retrieve table information: {str(err)}",
        }


@register_tool(
    name="db_query",
    domain="database",
    description=(
        "Execute a SQL query against the SQLite database. "
        "Under 'read' permission, only SELECT queries are permitted. "
        "Under 'read_write' permission, SELECT, INSERT, UPDATE, and DELETE are permitted."
    ),
    is_mutating=True,
    allowed_levels=("disabled", "read", "read_write"),
)
def db_query(
    query: str,
    params: Optional[List[Any]] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """Execute SQL query with granular permission boundaries for SELECT vs mutating commands."""
    if not query or not query.strip():
        return {
            "success": False,
            "error": "Query parameter cannot be empty.",
        }

    # 1. Resolve active permission level
    permissions = get_cached_tool_permissions()
    access_level = permissions.get("db_query")

    if not access_level:
        try:
            from app.models.mcp import MCPTool

            access_level = MCPTool.get_tool_permission("db_query") or "disabled"
        except Exception:
            access_level = "disabled"

    if access_level == "disabled":
        return {
            "success": False,
            "error": "Tool 'db_query' is disabled in Travel Assistant settings.",
        }

    # 2. Sanitise and validate SQL
    cleaned_sql = _clean_sql(query)
    if not cleaned_sql:
        return {
            "success": False,
            "error": "Query contains no executable SQL statements.",
        }

    if _has_multiple_statements(cleaned_sql):
        return {
            "success": False,
            "error": "Multiple SQL statements in a single call are not permitted.",
        }

    stmt_type = _extract_statement_type(cleaned_sql)

    # 3. Enforce permission boundary
    if access_level == "read":
        if stmt_type != "SELECT":
            return {
                "success": False,
                "error": (
                    f"Operation '{stmt_type}' rejected: tool 'db_query' is configured "
                    "with 'read' access, which only permits SELECT queries. "
                    "Configure 'read_write' access in the Web UI to execute mutating operations."
                ),
            }
    elif access_level == "read_write":
        if stmt_type != "SELECT" and stmt_type not in PERMITTED_MUTATING_STATEMENTS:
            return {
                "success": False,
                "error": (
                    f"Operation '{stmt_type}' rejected: only SELECT, INSERT, UPDATE, "
                    "and DELETE statements are permitted."
                ),
            }

    # 4. Execute SQL
    try:
        if stmt_type == "SELECT":
            max_rows = max(1, min(limit, 1000))
            cursor = db.execute_sql(cleaned_sql, params or ())
            columns = (
                [col[0] for col in cursor.description] if cursor.description else []
            )
            raw_rows = cursor.fetchmany(max_rows + 1)
            truncated = len(raw_rows) > max_rows
            if truncated:
                raw_rows = raw_rows[:max_rows]

            rows = [dict(zip(columns, r)) for r in raw_rows]
            return {
                "success": True,
                "type": "SELECT",
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
            }
        else:
            with db.atomic():
                cursor = db.execute_sql(cleaned_sql, params or ())
                rows_affected = cursor.rowcount
                last_insert_id = cursor.lastrowid if stmt_type == "INSERT" else None

            return {
                "success": True,
                "type": stmt_type,
                "rows_affected": rows_affected,
                "last_insert_id": last_insert_id,
            }
    except Exception as err:
        logger.warning("Database query execution failed: %s", err)
        return {
            "success": False,
            "error": str(err),
            "query": query,
        }


__all__ = [
    "db_get_table_info",
    "db_query",
]
