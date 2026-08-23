TRANSITIONS: dict[str, frozenset[str]] = {
    "backlog": frozenset({"todo", "canceled"}),
    "todo": frozenset({"backlog", "in_progress", "canceled"}),
    "in_progress": frozenset({"todo", "done", "canceled"}),
    "done": frozenset({"in_progress"}),
    "canceled": frozenset({"backlog"}),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())
