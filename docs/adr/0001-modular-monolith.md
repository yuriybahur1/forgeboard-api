# ADR 0001: Modular monolith

Status: accepted.

Keep domain modules in one deployable service and one transactional database. The current domain benefits from atomic cross-module workflows more than independent scaling. Module boundaries preserve a future extraction seam without distributed-system overhead.

