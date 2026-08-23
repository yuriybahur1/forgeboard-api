# ADR 0002: Async HTTP and synchronous workers

Status: accepted.

FastAPI uses async psycopg sessions for request concurrency. Celery uses independent synchronous psycopg sessions because its execution model is synchronous. Sessions are never shared across requests or tasks.

