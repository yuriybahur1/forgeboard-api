from __future__ import annotations

import socket
from typing import Any

import structlog
from celery import Task

from workstream.core.config import get_settings
from workstream.db.session import sync_session_factory
from workstream.infrastructure.celery_app import celery_app
from workstream.infrastructure.email import send_email
from workstream.infrastructure.outbox import ClaimedEvent, claim_events, mark_failed, mark_processed

logger = structlog.get_logger()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="workstream.outbox.dispatch",
    bind=True,
    max_retries=5,
    retry_backoff=True,
    retry_jitter=True,
)
def dispatch_outbox(self: Task[Any, Any], batch_size: int = 50) -> int:
    settings = get_settings()
    worker = f"{socket.gethostname()}:{self.request.id}"
    processed = 0
    events = claim_events(sync_session_factory, worker, batch_size, settings.outbox_claim_seconds)
    for event in events:
        try:
            deliver(event)
            mark_processed(sync_session_factory, event, worker)
            processed += 1
        except Exception as exc:
            mark_failed(sync_session_factory, event, worker, exc, settings.outbox_max_attempts)
            logger.warning("outbox_delivery_failed", event_id=str(event.id), topic=event.topic)
    return processed


def deliver(event: ClaimedEvent) -> None:
    settings = get_settings()
    payload = event.payload
    token = str(payload["token"])
    paths = {
        "email.verification": "verify-email",
        "email.password_reset": "reset-password",
        "email.invitation": "accept-invitation",
    }
    path = paths.get(event.topic)
    if path is None:
        raise ValueError(f"unsupported outbox topic: {event.topic}")
    send_email(
        settings,
        "action",
        str(payload["email"]),
        "Workstream account action",
        {"action_url": f"{settings.public_url}/{path}?token={token}"},
    )
