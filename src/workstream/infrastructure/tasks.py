import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from celery import Task
from sqlalchemy import select

from workstream.core.config import get_settings
from workstream.db.session import sync_session_factory
from workstream.infrastructure.celery_app import celery_app
from workstream.infrastructure.email import send_email
from workstream.modules.models import OutboxEvent

logger = structlog.get_logger()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="workstream.outbox.dispatch",
    bind=True,
    max_retries=5,
    retry_backoff=True,
    retry_jitter=True,
)
def dispatch_outbox(self: Task[Any, Any], batch_size: int = 50) -> int:
    worker = f"{socket.gethostname()}:{self.request.id}"
    processed = 0
    with sync_session_factory.begin() as db:
        events = list(
            db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.processed_at.is_(None),
                    OutboxEvent.failed_at.is_(None),
                    OutboxEvent.available_at <= datetime.now(UTC),
                )
                .order_by(OutboxEvent.occurred_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        for event in events:
            event.locked_at = datetime.now(UTC)
            event.locked_by = worker
        db.flush()
        for event in events:
            try:
                deliver(event)
                event.processed_at = datetime.now(UTC)
                processed += 1
            except Exception as exc:
                event.attempts += 1
                event.last_error = str(exc)[:2000]
                event.locked_at = None
                event.locked_by = None
                if event.attempts >= 10:
                    event.failed_at = datetime.now(UTC)
                else:
                    event.available_at = datetime.now(UTC) + timedelta(
                        seconds=min(3600, 2**event.attempts)
                    )
                logger.warning(
                    "outbox_delivery_failed",
                    event_id=str(event.id),
                    topic=event.topic,
                    attempts=event.attempts,
                )
    return processed


def deliver(event: OutboxEvent) -> None:
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
