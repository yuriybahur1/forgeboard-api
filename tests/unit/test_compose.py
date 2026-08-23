from pathlib import Path

import pytest
import yaml

from workstream.infrastructure.celery_app import celery_app

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def test_celery_beat_schedule_uses_writable_runtime_location() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    command = compose["services"]["beat"]["command"]
    schedule_option = next(option for option in command if option.startswith("--schedule="))

    assert schedule_option == "--schedule=/tmp/celerybeat-schedule"
    assert celery_app.conf.beat_schedule["dispatch-outbox"] == {
        "task": "workstream.outbox.dispatch",
        "schedule": 5.0,
    }
