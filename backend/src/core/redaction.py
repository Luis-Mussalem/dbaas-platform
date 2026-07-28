"""
Redaction of infrastructure details out of error text that reaches the API.

Some failures are recorded on a row the API later returns — ``Backup.error_message``
(BackupRead) and ``MaintenanceTask.result_summary`` (MaintenanceTaskRead). Those
strings come from ``pg_dump``/``pg_basebackup`` stderr or from psycopg, and both
routinely name the container host, the dynamically published port and the absolute
host path of the target file:

    connection to server at "localhost" (127.0.0.1), port 55004 failed: ...
    could not open output file "/home/op/dbaas/data/backups/<uuid>/logical/<uuid>.dump"

Those are the same details the routers deliberately withhold when they answer with
"Check server logs for details." — persisting them unredacted would hand the client
through one endpoint what another one refuses to say.

The rule applied here is *redact, don't drop*: the reason a command failed ("no space
left on device", "permission denied", "relation does not exist") is exactly what makes
the failure actionable in the UI, so it survives; only the topology is masked. The
untouched original always goes to the application log, which only the operator reads.
"""
import re

# Ordered: the URI rule must run before the host/port ones, otherwise a
# postgres://user:pw@host:5432/db would be partially rewritten and leak the rest.
_REDACTIONS = (
    # postgres:// URIs, with or without embedded credentials
    (re.compile(r"postgres(?:ql)?://\S+", re.IGNORECASE), "<uri>"),
    # 'at "host" (1.2.3.4), port 5432' — the shape libpq uses for connection errors
    (re.compile(r'at "[^"]*" \([^)]*\), port \d+', re.IGNORECASE), "at <host>, port <port>"),
    (re.compile(r'\bhost\s*"[^"]*"', re.IGNORECASE), 'host "<host>"'),
    (re.compile(r"\bport\s+\d+", re.IGNORECASE), "port <port>"),
    # Absolute POSIX paths (backup targets, socket directories). The lookbehind keeps
    # it from firing inside a word or on a decimal like "1.5/s".
    (re.compile(r"(?<![\w.])/[\w./-]{2,}"), "<path>"),
    # Bare IPv4 literals
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<ip>"),
)

# Ceiling for the stored message. pg_restore can emit hundreds of warning lines; the
# column exists for a human glance in the UI, not to archive the full transcript.
MAX_ERROR_LEN = 500

_FALLBACK = "Operation failed — see server logs for details."


def redact_error(message: str) -> str:
    """
    Strips host, port, IP, URI and filesystem details out of an error message.

    Returns a whitespace-collapsed, length-capped string safe to persist on a row
    the API returns. An empty or fully-redacted message falls back to a generic
    sentence rather than an empty field, so the UI always has something to show.
    """
    redacted = message.strip()
    for pattern, replacement in _REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    # Collapse the whitespace left behind so the UI shows one readable line.
    redacted = " ".join(redacted.split())
    if len(redacted) > MAX_ERROR_LEN:
        redacted = redacted[: MAX_ERROR_LEN - 1].rstrip() + "…"
    return redacted or _FALLBACK
