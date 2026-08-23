# Architecture

Workstream is a domain-oriented modular monolith. FastAPI owns the async request path; SQLAlchemy `AsyncSession` instances are request scoped. Routers invoke explicit workflows and own commit boundaries. Query helpers never commit. Tenant-owned rows are selected with organization scope, and non-members receive 404 to avoid confirming cross-tenant resource existence.

Access JWTs are short-lived and tied to database-backed sessions. Opaque refresh tokens are hashed at rest, rotated under row lock, and grouped into families; reuse revokes the family. Verification, reset, and invitation tokens are one-time hashed records.

Organization row locks serialize owner changes, preserving the final-owner invariant. Project counters allocate issue numbers with atomic `UPDATE ... RETURNING`. Issue mutations use a version predicate for optimistic concurrency. Invitation acceptance locks the invitation row and relies on the membership primary key for uniqueness.

Business mutations and outbox events commit together. Celery beat invokes dispatchers which claim batches using `FOR UPDATE SKIP LOCKED`. Delivery is at least once: failures back off and become terminal after ten attempts. Email consumers must tolerate duplicates; no exactly-once claim is made.

Request IDs live in structlog context variables and are cleared after each request. HTTP metrics use normalized route templates and status classes. Readiness checks PostgreSQL and Redis with deadlines; liveness has no external dependency.

