import pytest

from app.context import Deadline, ScanTimeout


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_deadline_counts_down():
    clock = Clock()
    deadline = Deadline(60, clock=clock)
    assert deadline.remaining() == 60
    clock.now += 45
    assert deadline.remaining() == 15
    assert not deadline.expired()
    deadline.check()


def test_engine_timeout_is_capped_by_remaining():
    clock = Clock()
    deadline = Deadline(1800, clock=clock)
    assert deadline.engine_timeout(300) == 300
    clock.now += 1700
    assert deadline.engine_timeout(300) == 100


def test_expired_deadline_raises():
    clock = Clock()
    deadline = Deadline(10, clock=clock)
    clock.now += 11
    assert deadline.remaining() == 0
    assert deadline.expired()
    assert deadline.engine_timeout(300) == 0
    with pytest.raises(ScanTimeout, match="Превышено общее время скана \\(10 с\\)"):
        deadline.check()
