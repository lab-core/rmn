"""Running a pass of a job one batch at a time (process_copy.batching)."""

import os

import pytest

from process_copy.batching import (
    FORK,
    SPAWN,
    FinishedBatch,
    InlineBatches,
    ProcessBatches,
    max_ram_gb,
    run_batch,
)


def talkative(n, events):
    for i in range(n):
        events.put(("done", i))
    events.put(("next", n))


def says_its_pid(events):
    events.put(("pid", os.getpid()))


def mute(events):
    pass


def killed(events):
    events.put(("done", 0))
    raise SystemExit(-9)


class Dying(InlineBatches):
    """A batch the kernel took down where SystemExit is raised."""

    def start(self, target, args):
        try:
            return super().start(target, args)
        except SystemExit as e:
            return FinishedBatch(e.code)


def test_run_batch_brings_back_everything_the_batch_said():
    received, exitcode = run_batch(talkative, (3,), InlineBatches())

    assert received == [("done", 0), ("done", 1), ("done", 2), ("next", 3)]
    assert exitcode == 0


def test_a_batch_that_said_nothing_is_not_waited_on_for_ever():
    # the queue of a batch that died (OOM kill, segfault) is never filled:
    # the executor used to block on it while the heartbeat kept the job alive
    received, exitcode = run_batch(mute, (), InlineBatches())

    assert received == []
    assert exitcode == 0


def test_what_a_dying_batch_said_before_it_died_is_kept():
    received, exitcode = run_batch(killed, (), Dying())

    assert received == [("done", 0)]
    assert exitcode == -9


def test_a_batch_really_runs_in_a_process_of_its_own():
    # what gives the memory back is the process ending, so this is the part
    # worth asserting rather than the events alone
    received, exitcode = run_batch(says_its_pid, (), ProcessBatches(SPAWN))

    assert exitcode == 0
    [(_, pid)] = received
    assert pid != os.getpid()


@pytest.mark.skipif(FORK is SPAWN, reason="no fork on this platform")
def test_the_reader_context_still_forks():
    # the recognition worker reads the boxes of the job from a module global
    # the executor set for it, which a spawned child would not inherit
    assert FORK.get_start_method() == "fork"


def test_the_memory_guard_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAX_RAM_GB", "4")
    assert max_ram_gb() == 4
    monkeypatch.delenv("MAX_RAM_GB")
    assert max_ram_gb() > 100  # no limit worth the name
