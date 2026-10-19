"""Running a long pass of a job one batch at a time.

Reading the copies (matricules and grades) and writing the cover pages both
walk hundreds of pages at 300 dpi. The imaging libraries do not give all of
that memory back, so a single process doing the whole job grows until the
container kills it -- job d98c2837 was OOM-killed at copy 314 of 546 while
finalizing. Both passes therefore stop their batch once it has used
``MAX_RAM_GB`` and let the next one start in a new process, which is what
actually returns the memory.

What they share, and what lives here, is the plumbing: start a batch, read
what it reports, and notice when it dies without reporting anything. What to
do then is not shared -- the reader gives up the rest of the job, the cover
pages skip the copy and carry on -- so each pass keeps its own loop.
"""

import collections
import multiprocessing
import os


# Spawn, not fork, for everything written since: the heartbeat that keeps a
# job from looking idle runs in a thread of the executor, and a child that
# inherits a lock it held deadlocks on its first allocation (on macOS it
# segfaults as soon as the imaging libraries are loaded). A batch pays an
# import to start, once every few hundred copies.
SPAWN = multiprocessing.get_context("spawn")

# The reader still forks: its worker reads the boxes of the job from
# process_copy.config, which the executor set for this job and a spawned
# child would not inherit (runtime.apply_template_boxes). Moving it to spawn
# means passing those boxes explicitly.
FORK = (multiprocessing.get_context("fork")
        if "fork" in multiprocessing.get_all_start_methods()
        else SPAWN)


def max_ram_gb():
    """How much memory a batch may use before it hands over to the next one.

    Returns:
        int: MAX_RAM_GB, or no limit worth the name when it is not set. The
             guard measures the container (see imaging.memory_used_gb), so it
             must stay under the memory limit of the pod.
    """
    return int(os.getenv("MAX_RAM_GB", "1000"))


class _ListQueue:
    """What an inline batch reports on: a list, not a pipe.

    A SimpleQueue would do, but nothing drains it while the batch runs in this
    very process, and a batch with more to say than the pipe holds would block
    on its own report.
    """

    def __init__(self):
        self._items = collections.deque()

    def put(self, item):
        self._items.append(item)

    def empty(self):
        return not self._items

    def get(self):
        return self._items.popleft()


class FinishedBatch:
    """A batch that has already run, with the interface of a Process.

    What InlineBatches hands back, and what a caller simulating a batch that
    died hands back with the exit code it wants.
    """

    def __init__(self, exitcode):
        self.exitcode = exitcode

    def join(self, timeout=None):
        pass


class ProcessBatches:
    """Each batch in a process of its own: what gives the memory back."""

    def __init__(self, context=SPAWN):
        self._context = context

    def queue(self):
        return self._context.SimpleQueue()

    def start(self, target, args):
        batch = self._context.Process(target=target, args=args)
        batch.start()
        return batch


class InlineBatches:
    """Each batch in the caller's process: the CLI without --detach, and tests.

    Nothing is reclaimed between batches this way, so it is not what a job of
    any size should run with.
    """

    def queue(self):
        return _ListQueue()

    def start(self, target, args):
        target(*args)
        return FinishedBatch(0)


def run_batch(target, args, batches=None):
    """Run one batch and bring back everything it said.

    Args:
        target (callable): the batch, called as ``target(*args, events)``; it
            reports on ``events`` as it goes and puts its result there last.
        args (tuple): the arguments of the batch, the queue excepted.
        batches (ProcessBatches|InlineBatches): how to run it; a process of
            its own by default.

    Returns:
        (list, int): what the batch put on the queue, in order, and its exit
        code -- 0 when it returned by itself, negative when it was killed
        (a batch that dies without reporting used to leave the caller waiting
        on a queue nothing would ever fill, while the heartbeat kept the job
        looking alive).
    """
    batches = batches or ProcessBatches()
    events = batches.queue()
    batch = batches.start(target, (*args, events))

    received = []

    def drain():
        while not events.empty():
            received.append(events.get())

    while True:
        batch.join(timeout=1)
        drain()
        if batch.exitcode is not None:
            drain()  # what it reported just before it ended
            break
    batch.join()
    return received, batch.exitcode
