"""Тесты сериализации Runtime и безопасной работы нескольких отправителей."""

from __future__ import annotations

import threading
import unittest
from dataclasses import dataclass
from typing import ClassVar

from ciao import (
    Automaton,
    AutomatonContext,
    AutomatonObject,
    Program,
    Runtime,
    RuntimeReentryError,
    RuntimeThreadAffinityError,
    State,
    action,
    provided_command,
    transition,
)


@dataclass
class CounterContext(AutomatonContext):
    count: int = 0


class BlockingCounter(Automaton[CounterContext]):
    ready = State(initial=True)
    entered: ClassVar[threading.Event] = threading.Event()
    release: ClassVar[threading.Event] = threading.Event()

    @provided_command
    def increment(self) -> None:
        ...

    @action
    def wait_and_increment(self, ctx: CounterContext) -> None:
        ctx.count += 1
        self.entered.set()
        self.release.wait(timeout=2)

    on_increment = transition(
        source=ready,
        event=increment,
        actions=(wait_and_increment,),
        target=ready,
    )


class ReentrantAutomaton(Automaton[CounterContext]):
    ready = State(initial=True)
    runtime: ClassVar[Runtime | None] = None

    @provided_command
    def fire(self) -> None:
        ...

    @action
    def reenter(self, ctx: CounterContext) -> None:
        assert self.runtime is not None
        self.runtime.step()

    on_fire = transition(
        source=ready,
        event=fire,
        actions=(reenter,),
        target=ready,
    )


class RuntimeThreadingTests(unittest.TestCase):
    def setUp(self) -> None:
        BlockingCounter.entered = threading.Event()
        BlockingCounter.release = threading.Event()

    def test_send_does_not_wait_for_active_step_and_snapshot_does(self) -> None:
        object_ref = AutomatonObject("counter", BlockingCounter, CounterContext())
        runtime = Runtime(Program(objects=(object_ref,)))
        runtime.send(object_ref, BlockingCounter.increment)
        execution = threading.Thread(target=runtime.step)
        execution.start()
        self.assertTrue(BlockingCounter.entered.wait(timeout=1))

        runtime.send(object_ref, BlockingCounter.increment)
        self.assertEqual(1, runtime.pending_messages)

        snapshot_done = threading.Event()
        snapshots: list[int] = []

        def take_snapshot() -> None:
            snapshots.append(runtime.snapshot(object_ref).context.count)
            snapshot_done.set()

        reader = threading.Thread(target=take_snapshot)
        reader.start()
        self.assertFalse(snapshot_done.wait(timeout=0.05))
        BlockingCounter.release.set()
        execution.join(timeout=1)
        reader.join(timeout=1)
        self.assertEqual([1], snapshots)

    def test_nested_step_from_action_raises_reentry_error(self) -> None:
        object_ref = AutomatonObject("nested", ReentrantAutomaton, CounterContext())
        runtime = Runtime(Program(objects=(object_ref,)))
        ReentrantAutomaton.runtime = runtime
        runtime.send(object_ref, ReentrantAutomaton.fire)

        with self.assertRaises(RuntimeReentryError):
            runtime.step()
        self.assertEqual("error", runtime.trace[-1].status.value)

    def test_affinity_rejects_execution_but_allows_send_from_worker(self) -> None:
        object_ref = AutomatonObject("counter", BlockingCounter, CounterContext())
        runtime = Runtime(Program(objects=(object_ref,)))
        lease = runtime._acquire_thread_affinity()
        errors: list[Exception] = []

        def worker() -> None:
            runtime.send(object_ref, BlockingCounter.increment)
            try:
                runtime.step()
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=1)
        self.assertEqual(1, runtime.pending_messages)
        self.assertIsInstance(errors[0], RuntimeThreadAffinityError)

        lease.dispose()
        BlockingCounter.release.set()
        runtime.step()


if __name__ == "__main__":
    unittest.main()
