"""Тесты общих типизированных источников payload."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from ciao import ConstantPayloadSource, FactoryPayloadSource, PayloadSource


@dataclass(frozen=True, slots=True)
class StartInput:
    values: tuple[int, ...]


class CustomPayloadSource(PayloadSource[StartInput]):
    def __init__(self, value: StartInput) -> None:
        super().__init__(StartInput)
        self.value = value
        self.read_count = 0

    def _read(self) -> StartInput:
        self.read_count += 1
        return self.value


class PayloadSourceTests(unittest.TestCase):
    def test_factory_reads_fresh_value_once_per_call(self) -> None:
        current = [1]
        calls = 0

        def factory() -> StartInput:
            nonlocal calls
            calls += 1
            return StartInput(tuple(current))

        source = FactoryPayloadSource(StartInput, factory)
        self.assertIs(StartInput, source.payload_type)
        self.assertEqual(StartInput((1,)), source.read())
        current.append(2)
        self.assertEqual(StartInput((1, 2)), source.read())
        self.assertEqual(2, calls)

    def test_constant_source_uses_payload_concrete_type(self) -> None:
        payload = StartInput((2, 4, 6))
        source = ConstantPayloadSource(payload)
        self.assertIs(StartInput, source.payload_type)
        self.assertIs(payload, source.read())

    def test_base_class_checks_custom_source_result(self) -> None:
        source = CustomPayloadSource(StartInput((7,)))
        self.assertEqual(StartInput((7,)), source.read())
        self.assertEqual(1, source.read_count)

    def test_factory_rejects_wrong_runtime_type(self) -> None:
        source = FactoryPayloadSource(StartInput, lambda: "wrong")
        with self.assertRaises(TypeError):
            source.read()

    def test_constructor_rejects_invalid_contract(self) -> None:
        with self.assertRaises(TypeError):
            FactoryPayloadSource("StartInput", lambda: StartInput(()))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            FactoryPayloadSource(StartInput, None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
