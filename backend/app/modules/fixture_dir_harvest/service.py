"""Local fixture-directory harvest.

Scans a configured local directory for supported fixture files, records the
manifest on a harvest task, and can feed each harvested file through the
existing ingest pipeline by creating a temporary source per file. No network
crawling is involved.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.parse_feed import parse_fixture
from app.repositories import canonical as canon_repo
from app.repositories import harvests as harvest_repo
from app.repositories import runs as runs_repo
from app.repositories import sources as sources_repo
from app.services.ingest_service import run_ingest

SUPPORTED_FORMATS = {
    ".json": "json",
    ".jsonl": "jsonl",
    ".xml": "xml",
}


def resolve_directory(directory: str | None) -> Path:
    """Resolve the requested local directory.

    Empty means the repository fixtures directory. A relative value is looked
    up under FIXTURES_DIR, so both ``fixtures`` and ``fixtures/demo`` work.
    Absolute local paths are accepted as-is.
    """
    text = (directory or "").strip()
    if not text:
        candidate = FIXTURES_DIR
    else:
        path = Path(text)
        if path.is_absolute():
            candidate = path
        else:
            normalized = text.removeprefix("./")
            if normalized == "fixtures":
                candidate = FIXTURES_DIR
            elif normalized.startswith("fixtures/"):
                candidate = FIXTURES_DIR / normalized[len("fixtures/") :]
            else:
                candidate = FIXTURES_DIR / normalized

    if not candidate.exists():
        raise ValueError(f"harvest directory not found: {candidate}")
    if not candidate.is_dir():
        raise ValueError(f"harvest path is not a directory: {candidate}")
    return candidate.resolve()


def scan_directory(root: Path, recursive: bool = True) -> tuple[list[Path], int]:
    """Return supported fixture files (sorted) and the ignored file count."""
    candidates = root.rglob("*") if recursive else root.glob("*")
    supported: list[Path] = []
    ignored = 0
    for path in candidates:
        if not path.is_file():
            continue
        fmt = SUPPORTED_FORMATS.get(path.suffix.lower())
        if fmt is None:
            ignored += 1
            continue
        supported.append(path)
    return sorted(supported, key=lambda p: str(p.relative_to(root))), ignored


def _storage_fixture_path(path: Path) -> str:
    """Keep repo fixtures relative; external files stay absolute."""
    try:
        return str(path.resolve().relative_to(FIXTURES_DIR))
    except ValueError:
        return str(path.resolve())


def _aggregate_ingest(conn: sqlite3.Connection, run_ids: list[int]) -> dict[str, Any]:
    """Aggregate ingest facts straight from runs/staging/conflicts tables."""
    unique_ids = sorted({int(r) for r in run_ids if r is not None})
    if not unique_ids:
        return {
            "run_ids": [],
            "parsed_count": 0,
            "upserted_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "conflict_count": 0,
            "skipped_count": 0,
            "staging_count": 0,
            "staging_by_disposition": {},
            "conflict_rows": 0,
            "canonical_count_after": canon_repo.count_items(conn),
        }

    placeholders = ",".join("?" for _ in unique_ids)
    run_rows = conn.execute(
        f"""
        SELECT id, status, parsed_count, upserted_count, conflict_count, skipped_count
        FROM runs WHERE id IN ({placeholders})
        """,
        unique_ids,
    ).fetchall()
    staging_rows = conn.execute(
        f"""
        SELECT disposition, COUNT(*) AS c
        FROM staging_rows WHERE run_id IN ({placeholders})
        GROUP BY disposition
        """,
        unique_ids,
    ).fetchall()
    conflict_rows = conn.execute(
        f"SELECT COUNT(*) AS c FROM conflicts WHERE run_id IN ({placeholders})",
        unique_ids,
    ).fetchone()["c"]

    by_disposition = {r["disposition"]: int(r["c"]) for r in staging_rows}
    staging_count = sum(by_disposition.values())
    run_statuses = [r["status"] for r in run_rows]

    return {
        "run_ids": unique_ids,
        "run_statuses": run_statuses,
        "parsed_count": sum(int(r["parsed_count"]) for r in run_rows),
        "upserted_count": sum(int(r["upserted_count"]) for r in run_rows),
        "inserted_count": int(by_disposition.get("insert", 0)),
        "updated_count": int(by_disposition.get("upsert", 0)),
        "conflict_count": sum(int(r["conflict_count"]) for r in run_rows),
        "skipped_count": sum(int(r["skipped_count"]) for r in run_rows),
        "staging_count": staging_count,
        "staging_by_disposition": by_disposition,
        "conflict_rows": int(conflict_rows),
        "canonical_count_after": canon_repo.count_items(conn),
    }


def _finalize(harvest_id: int, *, mode: str, ingest_ran: bool) -> dict[str, Any]:
    conn = connect()
    try:
        task = harvest_repo.get_task(conn, harvest_id)
        if not task:
            raise ValueError("harvest task not found")
        files = harvest_repo.list_files(conn, harvest_id)

        discovered = len(files)
        harvested = sum(1 for f in files if f["parse_status"] == "harvested")
        failed = sum(1 for f in files if f["parse_status"] == "failed")
        parsed_items = sum(int(f["parsed_count"]) for f in files)
        ignored = int(task["ignored_count"])
        ingest_failed_files = sum(
            1 for f in files if f["parse_status"] == "harvested" and f["ingest_status"] == "failed"
        )
        ingest_ok_files = sum(
            1 for f in files if f["parse_status"] == "harvested" and f["ingest_status"] == "ok"
        )
        ingest_runs = [f["run_id"] for f in files if f["run_id"] is not None]
        aggregate = _aggregate_ingest(conn, ingest_runs)
        canonical_before = int(task["canonical_count_before"])
        canonical_after = canon_repo.count_items(conn)
        delta = canonical_after - canonical_before

        ingest = {
            "status": (
                "not_run"
                if not ingest_ran
                else "partial" if ingest_failed_files else "ok"
            ),
            "run_count": len(aggregate["run_ids"]),
            "failed_file_count": ingest_failed_files,
            **aggregate,
            "canonical_count_before": canonical_before,
            "canonical_count_after": canonical_after,
            "canonical_delta": delta,
        }

        reconciliation = {
            "files_balance": discovered == harvested + failed,
            "harvested_files_ingested": (
                None if not ingest_ran else ingest_ok_files == harvested - ingest_failed_files
            ),
            "parsed_items_match_ingest": (
                None if not ingest_ran else parsed_items == int(ingest["parsed_count"])
            ),
            "staging_matches_ingest_parsed": (
                None if not ingest_ran else int(ingest["staging_count"]) == int(ingest["parsed_count"])
            ),
            "conflict_rows_match_conflict_count": (
                None
                if not ingest_ran
                else int(ingest["conflict_rows"]) == int(ingest["conflict_count"])
            ),
            "upsert_balance": (
                None
                if not ingest_ran
                else int(ingest["upserted_count"])
                == int(ingest["inserted_count"]) + int(ingest["updated_count"])
            ),
            "canonical_delta_matches_inserts": (
                None if not ingest_ran else delta == int(ingest["inserted_count"])
            ),
        }
        checks = [v for v in reconciliation.values() if isinstance(v, bool)]
        reconciliation["all_ok"] = all(checks) if checks else True

        if discovered == 0:
            status = "ok"
        elif harvested == 0:
            status = "failed"
        elif failed or ingest_failed_files or (ingest_ran and not reconciliation["all_ok"]):
            status = "partial"
        else:
            status = "ok"

        report = {
            "directory": task["directory"],
            "recursive": task["recursive"],
            "mode": mode,
            "discovered_count": discovered,
            "harvested_count": harvested,
            "failed_count": failed,
            "ignored_count": ignored,
            "parsed_items_count": parsed_items,
            "ingest": ingest,
            "reconciliation": reconciliation,
        }
        harvest_repo.finish_task(
            conn,
            harvest_id,
            status=status,
            discovered=discovered,
            harvested=harvested,
            failed=failed,
            ignored=ignored,
            parsed_items=parsed_items,
            canonical_after=canonical_after,
            report=report,
        )
        conn.commit()
        return get_harvest_detail(harvest_id, conn=conn)
    finally:
        conn.close()


def create_harvest(
    directory: str | None = "",
    *,
    recursive: bool = True,
    ingest: bool = True,
    mode: str = "incremental",
) -> dict[str, Any]:
    if mode not in ("incremental", "full"):
        raise ValueError("mode must be incremental or full")

    root = resolve_directory(directory)
    try:
        files, ignored = scan_directory(root, recursive)
    except OSError as exc:
        raise ValueError(f"cannot scan harvest directory: {exc}") from exc

    parsed: list[dict[str, Any]] = []
    for path in files:
        fmt = SUPPORTED_FORMATS[path.suffix.lower()]
        rel = str(path.relative_to(root))
        try:
            items = parse_fixture(path, fmt)
            parsed.append(
                {
                    "path": path,
                    "relative_path": rel,
                    "format": fmt,
                    "parse_status": "harvested",
                    "parsed_count": len(items),
                    "error": None,
                }
            )
        except Exception as exc:  # noqa: BLE001 - one bad file must not fail the batch
            parsed.append(
                {
                    "path": path,
                    "relative_path": rel,
                    "format": fmt,
                    "parse_status": "failed",
                    "parsed_count": 0,
                    "error": str(exc),
                }
            )

    conn = connect()
    try:
        before = canon_repo.count_items(conn)
        harvest_id = harvest_repo.create_task(
            conn,
            directory=str(root),
            recursive=recursive,
            canonical_count_before=before,
        )
        for record in parsed:
            harvest_repo.insert_file(
                conn,
                harvest_id=harvest_id,
                relative_path=record["relative_path"],
                fmt=record["format"],
                parse_status=record["parse_status"],
                parsed_count=record["parsed_count"],
                error=record["error"],
            )
        conn.execute(
            "UPDATE harvest_tasks SET ignored_count=? WHERE id=?",
            (ignored, harvest_id),
        )
        conn.commit()
    finally:
        conn.close()

    if ingest and any(r["parse_status"] == "harvested" for r in parsed):
        ingest_harvest(harvest_id, mode=mode)
        return get_harvest_detail(harvest_id)

    return _finalize(harvest_id, mode=mode, ingest_ran=False)


def ingest_harvest(harvest_id: int, *, mode: str = "incremental") -> dict[str, Any]:
    """Run the existing ingest pipeline for each harvested file."""
    if mode not in ("incremental", "full"):
        raise ValueError("mode must be incremental or full")

    conn = connect()
    try:
        task = harvest_repo.get_task(conn, harvest_id)
        if not task:
            raise ValueError("harvest task not found")
        files = harvest_repo.list_files(conn, harvest_id)
        harvest_repo.set_task_canonical_before(
            conn, harvest_id, canon_repo.count_items(conn)
        )
        conn.commit()
    finally:
        conn.close()

    for file_row in files:
        if file_row["parse_status"] != "harvested":
            continue
        path = Path(task["directory"]) / file_row["relative_path"]
        conn = connect()
        try:
            source_id = sources_repo.create_source(
                conn,
                name=f"Harvest #{harvest_id} · {file_row['relative_path']}",
                format=file_row["format"],
                fixture_path=_storage_fixture_path(path),
                note=f"目录采集自动临时源（harvest #{harvest_id}）",
            )
            conn.commit()
        finally:
            conn.close()

        try:
            run = run_ingest(source_id, mode)
        except Exception as exc:  # noqa: BLE001 - keep batch going
            run_id = _latest_run_id_for_source(source_id)
            conn = connect()
            try:
                harvest_repo.update_file_ingest(
                    conn,
                    file_id=file_row["id"],
                    source_id=source_id,
                    run_id=run_id,
                    ingest_status="failed",
                    ingest_error=str(exc),
                )
                conn.commit()
            finally:
                conn.close()
        else:
            conn = connect()
            try:
                harvest_repo.update_file_ingest(
                    conn,
                    file_id=file_row["id"],
                    source_id=source_id,
                    run_id=run["id"],
                    ingest_status="ok",
                )
                conn.commit()
            finally:
                conn.close()

    return _finalize(harvest_id, mode=mode, ingest_ran=True)


def _latest_run_id_for_source(source_id: int) -> int | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT MAX(id) AS id FROM runs WHERE source_id = ?", (source_id,)
        ).fetchone()
        return int(row["id"]) if row and row["id"] is not None else None
    finally:
        conn.close()


def get_harvest_detail(
    harvest_id: int,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    owns_conn = conn is None
    if conn is None:
        conn = connect()
    try:
        task = harvest_repo.get_task(conn, harvest_id)
        if not task:
            raise ValueError("harvest task not found")
        files = harvest_repo.list_files(conn, harvest_id)
        runs = []
        for file_row in files:
            if file_row["run_id"] is None:
                continue
            run = runs_repo.get_run(conn, int(file_row["run_id"]))
            if run:
                runs.append(run)
        return {**task, "files": files, "runs": runs}
    finally:
        if owns_conn:
            conn.close()


def list_harvests() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return harvest_repo.list_tasks(conn)
    finally:
        conn.close()
