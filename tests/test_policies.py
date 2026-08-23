from workstream.modules.work.router import TRANSITIONS


def test_status_transitions_are_explicit() -> None:
    assert "in_progress" in TRANSITIONS["todo"]
    assert "backlog" not in TRANSITIONS["done"]
    assert all(state not in destinations for state, destinations in TRANSITIONS.items())
