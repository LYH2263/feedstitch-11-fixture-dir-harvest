from __future__ import annotations

import json
import sqlite3
from typing import Any


def create_task(
    conn: sqlite3.Connection,
    *,
    directory: str,
    recursive: bool,
    canonical_count_before: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO harvest_tasks(
            directory, recursive, status, canonical_count_before, report_json, created_at
        ) VALUES (?,?, 'running', ?, '{}', datetime('now'))
        """,
        (directory, 1 if recursive else 0, canonical_count_before),
    )
    return int(cur.lastrowid)


def insert_file(
    conn: sqlite3.Connection,
    *,
    harvest_id: int,
    relative_path: str,
    fmt: str,
    parse_status: str,
    parsed_count: int,
    error: str | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO harvest_files(
            harvest_id, relative_path, format, parse_status, parsed_count, error, created_at
        ) VALUES (?,?,?,?,?,?, datetime('now'))
        """,
        (harvest_id, relative_path, fmt, parse_status, parsed_count, error),
    )
    return int(cur.lastrowid)


def update_file_ingest(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    source_id: int | None,
    run_id: int | None,
    ingest_status: str,
    ingest_error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE harvest_files
        SET source_id=?, run_id=?, ingest_status=?, ingest_error=?
        WHERE id=?
        """,
        (source_id, run_id, ingest_status, ingest_error, file_id),
    )


def set_task_canonical_before(conn: sqlite3.Connection, harvest_id: int, count: int) -> None:
    conn.execute(
        "UPDATE harvest_tasks SET canonical_count_before=? WHERE id=?",
        (count, harvest_id),
    )


def finish_task(
    conn: sqlite3.Connection,
    harvest_id: int,
    *,
    status: str,
    discovered: int,
    harvested: int,
    failed: int,
    ignored: int,
    parsed_items: int,
    canonical_after: int,
    report: dict[str, Any],
) -> None:
    conn.execute(
        """
        UPDATE harvest_tasks
        SET status=?, discovered_count=?, harvested_count=?, failed_count=?,
            ignored_count=?, parsed_items_count=?, canonical_count_after=?,
            report_json=?, finished_at=datetime('now')
        WHERE id=?
        """,
        (
            status,
            discovered,
            harvested,
            failed,
            ignored,
            parsed_items,
            canonical_after,
            json.dumps(report, ensure_ascii=False),
            harvest_id,
        ),
    )


def _task_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["recursive"] = bool(d["recursive"])
    d["report"] = json.loads(d.pop("report_json") or "{}")
    return d


def list_tasks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, directory, recursive, status, discovered_count, harvested_count,
               failed_count, ignored_count, parsed_items_count, canonical_count_before,
               canonical_count_after, report_json, created_at, finished_at
        FROM harvest_tasks ORDER BY id DESC
        """
    ).fetchall()
    return [_task_row(r) for r in rows]


def get_task(conn: sqlite3.Connection, harvest_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, directory, recursive, status, discovered_count, harvested_count,
               failed_count, ignored_count, parsed_items_count, canonical_count_before,
               canonical_count_after, report_json, created_at, finished_at
        FROM harvest_tasks WHERE id = ?
        """,
        (harvest_id,),
    ).fetchone()
    return _task_row(row) if row else None


def list_files(conn: sqlite3.Connection, harvest_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, harvest_id, relative_path, format, parse_status, parsed_count, error,
               source_id, run_id, ingest_status, ingest_error, created_at
        FROM harvest_files WHERE harvest_id = ? ORDER BY id
        """,
        (harvest_id,),
    ).fetchall()
    return [dict(r) for r in rows]
