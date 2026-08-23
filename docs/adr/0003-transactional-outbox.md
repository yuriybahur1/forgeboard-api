# ADR 0003: Transactional outbox

Status: accepted.

External side effects originate as outbox rows committed with business state. Concurrent dispatchers claim and lease rows with `SKIP LOCKED` in a short transaction, deliver outside the transaction, then finalize separately. Expired leases are reclaimable. A worker can deliver successfully and die before finalization, so delivery is at least once and SMTP duplicates remain possible. Failed events back off and remain inspectable after the bounded retry limit.
