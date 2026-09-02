from __future__ import annotations

from server.api.demo_jobs import DemoBatchStore


def test_batch_store_tracks_case_progress_and_terminal_status() -> None:
    store = DemoBatchStore(ttl_seconds=60)
    initial = store.create((("first", "payload one"), ("second", "payload two")))

    assert initial.status == "queued"
    assert initial.completed == 0
    assert store.mark_running(initial.batch_id, 0) is True
    running_case = store.snapshot(initial.batch_id)
    assert running_case is not None
    assert running_case.status == "running"
    assert running_case.current_name == "first"
    assert running_case.cases[0].status == "running"

    store.finish_case(initial.batch_id, 0, "completed", {"policy_action": "allow"})
    running = store.snapshot(initial.batch_id)
    assert running is not None
    assert running.status == "running"
    assert running.completed == 1
    assert running.current_name is None

    assert store.mark_running(initial.batch_id, 1) is True
    store.finish_case(initial.batch_id, 1, "completed", {"policy_action": "allow"})
    completed = store.snapshot(initial.batch_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.completed == 2


def test_expired_batch_does_not_return_payload() -> None:
    store = DemoBatchStore(ttl_seconds=0)
    created = store.create((("secret-case", "synthetic payload"),))

    expired = store.snapshot(created.batch_id)

    assert expired is not None
    assert expired.status == "expired"
    assert expired.cases[0].status == "expired"
    assert expired.cases[0].text == ""
