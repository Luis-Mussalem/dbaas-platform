"""
Request rate limiting (slowapi), keyed by client IP.

Two groups of endpoints are limited, for different reasons.

**Authentication** (`/auth/*`) is limited because it is unauthenticated and
guessable: login, registration and refresh are where credential stuffing lands.

**Query execution** (`/instances/{id}/query` and `/explain`) is limited because
each call does real work on a MONITORED database, not on the platform's own. Both
are authenticated and SELECT-only, so this isn't about authorization — it's that
`statement_timeout=30s` caps one query's duration but nothing caps the RATE, and a
tight loop of 30-second scans is a denial of service against the customer's
database delivered through our API. The limit is per IP and generous enough that a
person typing SQL into the console never notices it.

The limits themselves are declared at each endpoint with `@limiter.limit(...)`, so
the number sits next to the handler it governs rather than in a table far away.
Note that slowapi requires the decorated function to take a `request: Request`
parameter — that argument exists solely for this.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
