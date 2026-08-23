from celery import Celery

from workstream.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "workstream", broker=settings.redis_url, include=["workstream.infrastructure.tasks"]
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=60,
    task_soft_time_limit=45,
    worker_prefetch_multiplier=1,
    result_backend=None,
    beat_schedule={"dispatch-outbox": {"task": "workstream.outbox.dispatch", "schedule": 5.0}},
)
