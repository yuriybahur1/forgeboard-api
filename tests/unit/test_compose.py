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


def test_http_healthcheck_belongs_only_to_api_service() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    services = compose["services"]

    assert services["api"]["healthcheck"] == {
        "test": [
            "CMD",
            "python",
            "-c",
            ("import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"),
        ],
        "interval": "30s",
        "timeout": "3s",
    }
    assert "healthcheck" not in services["worker"]
    assert "healthcheck" not in services["beat"]
    assert "HEALTHCHECK" not in (ROOT / "Dockerfile").read_text()
