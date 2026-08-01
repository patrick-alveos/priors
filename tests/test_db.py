from pathlib import Path

from priors import db


def test_init_and_seed_idempotent(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    db.seed_owner(conn, "owner@example.com", "Owner")
    db.seed_owner(conn, "owner@example.com", "Owner")  # second call must not duplicate
    subs = db.active_subscribers(conn)
    assert len(subs) == 1
    assert subs[0]["email"] == "owner@example.com"


def test_schema_tables_exist(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"articles", "issues", "market_snapshots", "subscribers"} <= tables
