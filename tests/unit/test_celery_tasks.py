import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from workstream.infrastructure import tasks
from workstream.infrastructure.outbox import ClaimedEvent

pytestmark = pytest.mark.unit


def test_tasks_module_imports_with_runtime_task_annotation() -> None:
    module = importlib.import_module("workstream.infrastructure.tasks")

    assert module.dispatch_outbox.name == "workstream.outbox.dispatch"


def test_dispatch_outbox_delivers_and_marks_event_processed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = ClaimedEvent(uuid4(), "email.verification", {"email": "user@example.com"})
    delivered: list[ClaimedEvent] = []
    processed: list[tuple[ClaimedEvent, str]] = []
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: SimpleNamespace(outbox_claim_seconds=30, outbox_max_attempts=4),
    )
    monkeypatch.setattr(tasks.socket, "gethostname", lambda: "worker-host")
    monkeypatch.setattr(tasks, "claim_events", lambda sessions, worker, size, lease: [event])
    monkeypatch.setattr(tasks, "deliver", delivered.append)
    monkeypatch.setattr(
        tasks,
        "mark_processed",
        lambda sessions, claimed, worker: processed.append((claimed, worker)),
    )

    assert tasks.dispatch_outbox.run(batch_size=10) == 1
    assert delivered == [event]
    assert processed[0][0] == event
    assert processed[0][1] == "worker-host:None"


def test_dispatch_outbox_marks_delivery_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    event = ClaimedEvent(uuid4(), "email.verification", {"email": "user@example.com"})
    failure = OSError("SMTP unavailable")
    failed: list[tuple[ClaimedEvent, str, Exception, int]] = []
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: SimpleNamespace(outbox_claim_seconds=30, outbox_max_attempts=4),
    )
    monkeypatch.setattr(tasks, "claim_events", lambda sessions, worker, size, lease: [event])

    def fail_delivery(claimed: ClaimedEvent) -> None:
        assert claimed == event
        raise failure

    monkeypatch.setattr(tasks, "deliver", fail_delivery)
    monkeypatch.setattr(
        tasks,
        "mark_failed",
        lambda sessions, claimed, worker, error, attempts: failed.append(
            (claimed, worker, error, attempts)
        ),
    )

    assert tasks.dispatch_outbox.run() == 0
    assert failed[0][0] == event
    assert failed[0][2] is failure
    assert failed[0][3] == 4


def test_deliver_invitation_sends_expected_action_url(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[object, str, str, str, dict[str, str]]] = []
    settings = SimpleNamespace(public_url="https://workstream.example")
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks, "send_email", lambda *args: sent.append(args))
    event = ClaimedEvent(
        uuid4(),
        "email.invitation",
        {"email": "invitee@example.com", "token": "invitation-token"},
    )

    tasks.deliver(event)

    assert sent == [
        (
            settings,
            "action",
            "invitee@example.com",
            "Workstream account action",
            {"action_url": ("https://workstream.example/accept-invitation?token=invitation-token")},
        )
    ]


def test_deliver_rejects_unsupported_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tasks, "get_settings", lambda: SimpleNamespace(public_url="https://workstream.example")
    )
    event = ClaimedEvent(uuid4(), "email.unknown", {"email": "user@example.com", "token": "x"})

    with pytest.raises(ValueError, match=r"unsupported outbox topic: email\.unknown"):
        tasks.deliver(event)
