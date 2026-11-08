# Руководства по использованию

Этот раздел предназначен для практических инструкций по работе с библиотекой.

## Сценарии использования

1. Установка проекта и запуск тестов.
2. Объявление первого автоматного класса.
3. Создание объектов и соединение требуемых/предоставляемых операций.
4. Пошаговое выполнение через `step()` и запуск через `run()`.
5. Чтение состояния и трассы исполнения.
6. Запуск примера суммы массива без GUI.
7. Подключение Tkinter-визуализации и собственного виджета.

Первая headless-реализация готова. Техническое задание остаётся нормативным описанием поведения, а фрагмент ниже показывает согласованный декларативный API.

## Согласованный эскиз декларации перехода

Ниже показана форма API, которую следует использовать при проектировании первого сквозного примера. Пользовательский контекст наследуется от `AutomatonContext`; точный способ задания начальных значений и объявления управляющих состояний будет уточнён отдельно.

```python
from dataclasses import dataclass


@dataclass
class ControllerContext(AutomatonContext):
    values: list[int]
    index: int = 0
    total: int = 0


class Controller(Automaton[ControllerContext]):
    @provided_command
    def tick(self) -> None:
        ...

    @guard
    def has_next(self, ctx: "ControllerContext") -> bool:
        return ctx.index < len(ctx.values)

    @action
    def add_current(self, ctx: "ControllerContext") -> None:
        ctx.total += ctx.values[ctx.index]

    @action
    def advance(self, ctx: "ControllerContext") -> None:
        ctx.index += 1

    step = transition(
        source=RUNNING,
        event=tick,
        guard=has_next,
        actions=(add_current, advance),
        target=RUNNING,
    )
```

На этапе компиляции проверяются аннотации параметров и результата. Декоратор `@guard` фиксирует контракт возврата `bool`, но не гарантирует отсутствие побочных эффектов внутри произвольного Python-кода.

Требуемая команда публикуется через stateless-интерфейс автомата с явной передачей контекста: `self.emit(ctx, self.required_operation, ...)`. Требуемый запрос вызывается аналогично через `self.query(ctx, self.required_query, ...)`. Контекст не предоставляет публичных методов управления очередью.

Цельный исполняемый пример с двумя автоматами, состояниями, переходами, соединением и headless-запуском находится в [`examples/test_mock_sample.py`](../../examples/test_mock_sample.py). Короткая точка запуска — `examples/array_sum.py`.

## Среда первой реализации

- Python 3.11 или новее;
- сборка через `pyproject.toml`;
- установка для разработки: `pip install -e .`;
- тесты: `pytest`;
- первая вертикальная итерация работает без Tkinter, визуализация подключается после стабилизации ядра.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe examples\array_sum.py
.\.venv\Scripts\python.exe examples\array_sum_tk.py
```
