import importlib

import pytest

pytestmark = pytest.mark.unit


def test_tasks_module_imports_with_runtime_task_annotation() -> None:
    module = importlib.import_module("workstream.infrastructure.tasks")

    assert module.dispatch_outbox.name == "workstream.outbox.dispatch"
