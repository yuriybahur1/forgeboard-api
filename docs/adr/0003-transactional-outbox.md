# ADR 0003: Transactional outbox

Status: accepted.

External side effects originate as outbox rows committed with business state. Concurrent dispatchers claim with `SKIP LOCKED`; retry and worker failure mean delivery is at least once. Consumers are designed to tolerate duplicate delivery. Failed events remain inspectable rather than being discarded.
