"""
Tests for core.redaction — infrastructure details must not ride out on a row the
API returns.

The routers already answer failures with "Check server logs for details."
precisely so a client never learns the container host, the dynamically published
port or the absolute backup path. But `Backup.error_message` and
`MaintenanceTask.result_summary` are columns that BackupRead / MaintenanceTaskRead
hand straight back — writing raw stderr into them handed the client through one
endpoint what another one refuses to say.

Two properties are pinned down here: the topology is masked, and the actionable
reason survives (a redactor that returned "" would be safe and useless).
"""
from src.core.redaction import MAX_ERROR_LEN, redact_error


def test_libpq_connection_error_loses_host_port_and_ip():
    raw = (
        'connection to server at "localhost" (127.0.0.1), port 55004 failed: '
        "Connection refused"
    )
    out = redact_error(raw)

    assert "127.0.0.1" not in out
    assert "55004" not in out
    # ...but the operator still learns WHY it failed.
    assert "Connection refused" in out


def test_absolute_paths_are_masked():
    raw = (
        'pg_dump: error: could not open output file '
        '"/home/op/dbaas-platform/data/backups/9f2/logical/ab3.dump": '
        "No space left on device"
    )
    out = redact_error(raw)

    assert "/home/op" not in out
    assert "dbaas-platform" not in out
    assert "No space left on device" in out


def test_connection_uri_with_credentials_is_dropped_whole():
    raw = "could not connect using postgresql://inst_ab3:s3cr3t@127.0.0.1:55004/db_ab3"
    out = redact_error(raw)

    assert "s3cr3t" not in out
    assert "inst_ab3" not in out
    assert "<uri>" in out


def test_message_is_capped():
    out = redact_error("pg_restore: warning: errors ignored on restore. " * 100)
    assert len(out) <= MAX_ERROR_LEN


def test_multiline_stderr_becomes_one_line():
    out = redact_error("pg_dump: error: line one\n\n  line two\n")
    assert "\n" not in out
    assert out == "pg_dump: error: line one line two"


def test_empty_message_falls_back_to_a_sentence():
    """A blank field in the UI reads as "no error"; it must say something."""
    assert redact_error("   ") == "Operation failed — see server logs for details."


def test_plain_sql_errors_survive_untouched():
    """The common case must not be mangled — most failures name no infrastructure."""
    raw = 'relation "orders" does not exist'
    assert redact_error(raw) == raw


def test_decimals_are_not_mistaken_for_paths():
    """The path rule must not fire inside ordinary numbers or ratios."""
    out = redact_error("timeout after 1.5s, ratio 3/4 exceeded")
    assert "1.5s" in out
    assert "3/4" in out
