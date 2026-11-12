import json

import pytest

from app import db as db_module
from app import seed
from app.db import connect
from app.modules.fixture_dir_harvest import (
    create_harvest,
    get_harvest_detail,
    ingest_harvest,
    list_harvests,
)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "app.db")
    seed.init_db()
    return tmp_path / "app.db"


def test_harvest_fixtures_ingests_and_reconciles(isolated_db):
    result = create_harvest("fixtures", recursive=True, ingest=True)

    assert result["status"] == "ok"
    assert result["discovered_count"] == 3
    assert result["harvested_count"] == 3
    assert result["failed_count"] == 0
    assert result["parsed_items_count"] == 8
    assert result["canonical_count_before"] == 0
    assert result["canonical_count_after"] == 7

    ingest = result["report"]["ingest"]
    assert ingest["parsed_count"] == 8
    assert ingest["upserted_count"] == 7
    assert ingest["inserted_count"] == 7
    assert ingest["conflict_count"] == 1
    assert ingest["staging_count"] == 8
    assert ingest["conflict_rows"] == 1
    assert ingest["canonical_delta"] == 7
    assert result["report"]["reconciliation"]["all_ok"] is True

    # Same-key, non-key divergence must be quarantined, not overwrite Canonical.
    conn = connect()
    try:
        row = conn.execute(
            "SELECT price FROM canonical_items WHERE business_key='SKU-1001'"
        ).fetchone()
        assert row["price"] == 129.0
        assert conn.execute("SELECT COUNT(*) c FROM conflicts").fetchone()["c"] == 1
    finally:
        conn.close()

    # Task and manifest survive a fresh read (page refresh / process restart).
    assert len(list_harvests()) == 1
    detail = get_harvest_detail(result["id"])
    assert len(detail["files"]) == 3
    assert len(detail["runs"]) == 3


def test_second_harvest_does_not_overwrite_and_still_reconciles(isolated_db):
    create_harvest("fixtures", ingest=True)
    again = create_harvest("fixtures", ingest=True)

    ingest = again["report"]["ingest"]
    assert ingest["upserted_count"] == 0
    assert ingest["conflict_count"] == 1
    assert ingest["skipped_count"] == 7
    assert ingest["canonical_delta"] == 0
    assert again["report"]["reconciliation"]["all_ok"] is True


def test_scan_only_then_explicit_ingest(isolated_db):
    scanned = create_harvest("fixtures", ingest=False)

    assert scanned["report"]["ingest"]["status"] == "not_run"
    assert scanned["parsed_items_count"] == 8
    assert scanned["report"]["reconciliation"]["files_balance"] is True

    ingested = ingest_harvest(scanned["id"])
    assert ingested["report"]["ingest"]["parsed_count"] == 8
    assert ingested["report"]["reconciliation"]["all_ok"] is True


def test_parse_failure_is_isolated_and_batch_continues(isolated_db, tmp_path):
    feed_dir = tmp_path / "feeds"
    feed_dir.mkdir()
    good = feed_dir / "good.json"
    good.write_text(
        json.dumps(
            [
                {
                    "business_key": "TMP-1",
                    "title": "Good",
                    "price": 1.0,
                    "category": "c",
                    "event_ts": "2026-11-01T00:00:00Z",
                    "source_revision": 1,
                }
            ]
        ),
        encoding="utf-8",
    )
    bad = feed_dir / "bad.jsonl"
    bad.write_text('{"business_key":"TMP-2"}\n', encoding="utf-8")
    ignored = feed_dir / "notes.txt"
    ignored.write_text("not a feed", encoding="utf-8")

    result = create_harvest(str(feed_dir), ingest=True)

    assert result["status"] == "partial"
    assert result["discovered_count"] == 2
    assert result["harvested_count"] == 1
    assert result["failed_count"] == 1
    assert result["ignored_count"] == 1
    assert result["report"]["ingest"]["parsed_count"] == 1
    assert result["report"]["ingest"]["run_count"] == 1
    failed_files = [f for f in result["files"] if f["parse_status"] == "failed"]
    assert failed_files and failed_files[0]["error"]
