"""Phase 9.2: the PII sweep finds planted PII in artifacts, CSV cells, drafts and the DB."""

from __future__ import annotations

import sqlite3

from scripts import pii_sweep


def test_sweep_clean_dir_passes(tmp_path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "notes.md").write_text(
        "2026-10-05 | Nominee Updates | 11:00 | NL-A742 | TENTATIVE | PULSE-2026-W40\n"
        "Caller: [REDACTED]\n"
    )
    findings, scanned = pii_sweep.sweep(tmp_path, None)
    assert findings == [] and scanned["artifacts/notes.md"] == 2


def test_sweep_finds_planted_pii_everywhere(tmp_path):
    art = tmp_path / "artifacts"
    (art / "drafts").mkdir(parents=True)
    (art / "notes.md").write_text("ok line\ncall me on 9876543210\n")
    (tmp_path / "reviews.csv").write_text("review_id,text\nr1,my email is jane.doe@example.com\n")
    (art / "drafts" / "NL-A742-booking.eml").write_text(
        "To: advisor@example.com\nSubject: [Pre-booking] NL-A742\n\nCaller PAN ABCPD1234E\n"
    )
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "amc.md").write_text("AMC helpline 9876543210\n")
    db = tmp_path / "suite.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE audit_log (details_json TEXT)")
    con.execute('INSERT INTO audit_log VALUES (\'{"note": "my number is 9123456789"}\')')
    con.commit()
    con.close()

    findings, _ = pii_sweep.sweep(tmp_path, db)
    locs = {
        f.location.rsplit(":", 1)[0] if f.location.startswith("db:") else f.location
        for f in findings
    }
    assert "artifacts/notes.md:2" in locs
    assert "reviews.csv:2:text" in locs
    assert "artifacts/drafts/NL-A742-booking.eml:body:1" in locs
    assert "db:audit_log:1" in locs
    assert not any(loc.startswith("corpus/") for loc in locs)  # public source docs
    assert not any("Subject" in loc or "To" in loc for loc in locs)


def test_sweep_cli_exit_code(tmp_path, capsys):
    assert pii_sweep.main(["--data-dir", str(tmp_path), "--db", str(tmp_path / "none.db")]) == 0
    (tmp_path / "x.txt").write_text("pan ABCPD1234E\n")
    assert pii_sweep.main(["--data-dir", str(tmp_path), "--db", str(tmp_path / "none.db")]) == 1
    out = capsys.readouterr().out
    assert "ABCPD1234E" not in out and "x.txt:1" in out
