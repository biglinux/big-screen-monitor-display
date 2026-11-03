import json

import pytest

from bsmd import health


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_valid_and_invalid_transitions():
    machine = health.LinkStateMachine()
    machine.to(health.RECOVERING)
    machine.to(health.HEALTHY)
    machine.to(health.DEGRADED)
    machine.to(health.HEALTHY)
    with pytest.raises(health.InvalidTransition):
        machine.to(health.FAILED)
    machine.to(health.RECOVERING)
    machine.to(health.RETRYING)
    machine.to(health.FAILED)
    assert [h[2] for h in machine.history][-3:] == [health.RECOVERING, health.RETRYING, health.FAILED]


def test_every_state_can_stop():
    for state, targets in health.TRANSITIONS.items():
        if state != health.STOPPED:
            assert health.STOPPED in targets


def test_backoff_grows_and_caps():
    backoff = health.Backoff(base=1, factor=2, cap=10, jitter=0)
    assert [backoff.next_delay() for _ in range(6)] == [1, 2, 4, 8, 10, 10]
    backoff.reset()
    assert backoff.next_delay() == 1


def test_heartbeat_detects_stuck_operation_and_missing_progress():
    clock = Clock()
    beat = health.Heartbeat("transport", clock)
    beat.begin("present")
    clock.t += 5
    assert beat.stalled(progress_timeout=60, op_timeout=10) is None
    clock.t += 6
    assert "present" in beat.stalled(progress_timeout=60, op_timeout=10)
    beat.end(True)
    assert beat.stalled(progress_timeout=60, op_timeout=10) is None
    clock.t += 61
    assert "no progress" in beat.stalled(progress_timeout=60, op_timeout=10)


def test_static_image_is_not_a_stall():
    """An iteration that decided nothing changed still counts as progress."""
    clock = Clock()
    beat = health.Heartbeat("transport", clock)
    for _ in range(100):
        clock.t += 1
        beat.progress()
    assert beat.stalled(5, 5) is None


def test_incident_log_is_bounded_on_disk(tmp_path):
    path = str(tmp_path / "incidents.jsonl")
    log = health.IncidentLog(path, maxlen=10, max_file_lines=20)
    for index in range(55):
        log.record("x", "warning", f"n{index}", attempts=index)
    assert len(log.recent(100)) == 10
    lines = open(path).read().splitlines()
    assert len(lines) <= 20
    assert json.loads(lines[-1])["message"] == "n54"
    reloaded = health.IncidentLog(path, maxlen=10)
    assert reloaded.recent(1)[0]["message"] == "n54"
