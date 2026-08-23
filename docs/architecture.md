# Architecture

Workstream is a domain-oriented modular monolith. FastAPI owns the async request path; SQLAlchemy `AsyncSession` instances are request scoped. Routers invoke explicit workflows and own commit boundaries. Query helpers never commit. Tenant-owned rows are selected with organization scope, and non-members receive 404 to avoid confirming cross-tenant resource existence.

Access JWTs are short-lived and reference a stable logical session family. Rotated refresh credentials are separate rows hidden from session listings; reuse revokes the entire logical session. Current logout revokes only the JWT's session, while global logout revokes all families. Verification, reset, and invitation tokens are one-time hashed records.

Organization row locks serialize owner changes, preserving the final-owner invariant. Project counters allocate issue numbers with atomic `UPDATE ... RETURNING`. Issue mutations use a version predicate for optimistic concurrency. Invitation acceptance locks the invitation row and relies on the membership primary key for uniqueness.

Business mutations and outbox events commit together. Celery beat invokes dispatchers which claim batches using `FOR UPDATE SKIP LOCKED` in a short transaction and commit their leases. SMTP delivery occurs outside any database transaction; success or retry state is finalized in another short transaction. Stale leases are reclaimable. Delivery is at least once: if SMTP succeeds and the worker dies before finalization, an email can be repeated. Successful delivery removes raw token material from the outbox payload.

The Redis Lua limiter protects login, password-reset request, verification resend, and invitation creation. Keys contain a hashed account identifier and direct peer address. Security-sensitive operations fail closed with a sanitized 503 if Redis is unavailable; readiness also reports Redis degradation.

Request IDs live in structlog context variables and are cleared after each request. HTTP metrics use normalized route templates and status classes. Readiness checks PostgreSQL and Redis with deadlines and returns per-dependency state; liveness has no external dependency.
