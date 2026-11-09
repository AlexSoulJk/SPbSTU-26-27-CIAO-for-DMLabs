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
8. Экспорт декларативной программы в draw.io.

Первая headless-реализация готова. Техническое задание остаётся нормативным описанием поведения, а фрагмент ниже показывает согласованный декларативный API.

## Согласованный эскиз декларации перехода

Ниже показана форма API первого сквозного примера. Пользовательский контекст наследуется от `AutomatonContext`, а роль автомата выбирается через Generic-базу.

```python
from dataclasses import dataclass

from ciao import (
    AutomatonContext,
    ControllerAutomaton,
    Emit,
    State,
    action,
    guard,
    provided_command,
    required_command,
    transition,
)


@dataclass
class ControllerContext(AutomatonContext):
    values: list[int]
    index: int = 0
    total: int = 0


class Controller(ControllerAutomaton[ControllerContext]):
    idle = State(initial=True)
    running = State()
    done = State(final=True)

    @provided_command(external=True)
    def start(self) -> None:
        ...

    @provided_command
    def tick(self) -> None:
        ...

    @required_command
    def draw(self, total: int) -> None:
        ...

    @guard
    def has_next(self, ctx: ControllerContext) -> bool:
        return ctx.index < len(ctx.values)

    @action
    def add_current(self, ctx: ControllerContext) -> None:
        ctx.total += ctx.values[ctx.index]

    @action
    def advance(self, ctx: ControllerContext) -> None:
        ctx.index += 1

    @action(emit=draw)
    def publish(self, ctx: ControllerContext, emit: Emit) -> None:
        emit(total=ctx.total)

    on_start = transition(source=idle, event=start, target=running)

    step = transition(
        source=running,
        event=tick,
        guard=has_next,
        actions=(add_current, advance, publish),
        target=running,
    )
```

На этапе компиляции проверяются аннотации параметров и результата. Декоратор `@guard` фиксирует контракт возврата `bool`, но не гарантирует отсутствие побочных эффектов внутри произвольного Python-кода.

Требуемая команда указывается в `@action(emit=...)`, а Runtime внедряет временный `Emit`. Вызов `emit(...)` не требует повторно указывать команду или `ctx`. Для нескольких команд применяется `@action(emits=(draw, log))` и вызов `emits[self.draw](...)`. Требуемый запрос по-прежнему вызывается через `self.query(ctx, self.required_query, ...)`. Контекст не предоставляет публичных методов управления очередью.

Цельный исполняемый пример с двумя автоматами, состояниями, переходами, соединением и headless-запуском находится в [`examples/test_mock_sample.py`](../../examples/test_mock_sample.py). Короткая точка запуска — `examples/array_sum.py`.

В актуальном примере Controller находится в `running`, пока ожидает пользовательский `tick`. Оба исходящих перехода основаны на одной бинарной проверке `index >= len(values)`: если текущий элемент существует, он прибавляется к сумме и Controller переходит в `publishing`; если индекс уже вышел за границу, Controller переходит прямо в `done`. В состоянии `publishing` он ожидает команду `draw_completed` от View. View посылает её после применения снимка, поэтому возврат в `running` происходит через FIFO автоматически и не требует второго нажатия кнопки.

Tkinter-пример при запуске сначала показывает настоящее начальное состояние `idle`. Кнопка `Init` отправляет команду `start`; после перехода в `running` она исчезает, а на её месте появляется кнопка «Следующий шаг», отправляющая пользовательскую команду `tick`. Общий адаптер событий находится в `ciao.visualization`, а конкретное представление этого примера импортируется из `ciao.visualization.array_sample`.

## Экспорт в draw.io

Экспортер принимает уже объявленный `Program`; вручную дублировать состояния или связи не требуется:

```python
from ciao.visualization.drawio import export_program_drawio
from examples.test_mock_sample import build_sample

sample = build_sample()
path = export_program_drawio(sample.program, "sum_program.drawio")
print(path)
```

Каталог назначения должен существовать. Повторный вызов атомарно заменяет прежний файл. Операция `start`, объявленная через `@provided_command(external=True)`, отображается внешним lollipop над блоком и соединяется с начальным состоянием. Несвязанные команды располагаются у нижней границы и подписываются коротким именем (`tick`, `reset`).

Операции из `Program.connections` отображаются в промежутке между автоматами как socket+ball: половина required завершается `halfCircle`, половина provided — `oval`, а короткая подпись располагается над общим узлом. В примере видны две связи: `draw` от Controller к View и подтверждение `draw_completed` в обратном направлении. Для запросов в подписи дополнительно сохраняются параметры и возвращаемый тип из проверенной `OperationSignature`.

Фон области автомата остаётся белым. Цвет роли применяется к состояниям и переходам: голубой для `Controller`, зелёный для `View`. Отдельная чёрная начальная точка не создаётся; начальное состояние определяется декларацией `State(initial=True)`.

## Среда первой реализации

- Python 3.11 или новее;
- сборка через `pyproject.toml`;
- установка для разработки: `pip install -e .`;
- тесты: `pytest`;
- runtime работает без Tkinter; GUI и draw.io остаются необязательными слоями.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe examples\array_sum.py
.\.venv\Scripts\python.exe examples\array_sum_tk.py
.\.venv\Scripts\python.exe examples\export_drawio.py
```
