"""Generate docs/architecture/db_schema.md from the live DuckDB information_schema.

Read-only. Regenerate whenever the schema changes:
    .venv/Scripts/python.exe scripts/gen_db_schema_doc.py
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb

DB = Path("data/market_data.duckdb")
OUT = Path("docs/architecture/db_schema.md")


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    objs = con.execute(
        """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_type, table_name
        """
    ).fetchall()

    cols_by_table: dict[str, list[tuple[str, str, str]]] = {}
    for name, _ in objs:
        cols = con.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = ?
            ORDER BY ordinal_position
            """,
            [name],
        ).fetchall()
        cols_by_table[name] = cols

    counts: dict[str, int] = {}
    for name, ttype in objs:
        if ttype == "BASE TABLE":
            counts[name] = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    con.close()

    tables = [n for n, t in objs if t == "BASE TABLE"]
    views = [n for n, t in objs if t == "VIEW"]

    lines: list[str] = []
    w = lines.append
    w("# DB schema reference (generated)")
    w("")
    w(f"> Auto-generated {dt.date.today().isoformat()} from `{DB.as_posix()}` "
      "`information_schema` by `scripts/gen_db_schema_doc.py`. **Do not hand-edit** — "
      "rerun the script. Row counts are `COUNT(*)` at generation time.")
    w("")
    w(f"{len(tables)} base tables · {len(views)} views. "
      "Column types are DuckDB types; `NULL?` = column is nullable "
      "(not whether it's actually populated — see memory for 100%-NULL columns "
      "like `adj_close`/`vwap`/`listing_date`).")
    w("")

    def render(name: str, is_view: bool) -> None:
        hdr = f"### `{name}`"
        if not is_view:
            hdr += f"  — {counts[name]:,} rows"
        w(hdr)
        w("")
        w("| column | type | NULL? |")
        w("|---|---|---|")
        for col, dtype, nullable in cols_by_table[name]:
            w(f"| {col} | {dtype} | {'yes' if nullable == 'YES' else 'no'} |")
        w("")

    w("## Base tables")
    w("")
    for name in tables:
        render(name, is_view=False)

    w("## Views")
    w("")
    for name in views:
        render(name, is_view=True)

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}: {len(tables)} tables, {len(views)} views")


if __name__ == "__main__":
    main()
