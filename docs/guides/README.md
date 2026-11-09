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
    Query,
    State,
    action,
    guard,
    provided_command,
    required_command,
    required_query,
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

    @guard(text="существует следующий элемент")
    def has_next(self, ctx: ControllerContext) -> bool:
        return ctx.index < len(ctx.values)

    @action(text="прибавляет текущий элемент")
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

    finish = transition(
        source=running,
        event=tick,
        otherwise=True,
        target=done,
    )
```

На этапе компиляции проверяются аннотации параметров и результата. Декоратор `@guard` фиксирует контракт возврата `bool`, но не гарантирует отсутствие побочных эффектов внутри произвольного Python-кода. Необязательный `text="..."` у `@guard` и `@action` используется только как понятное человеку описание на диаграмме; без него показывается обычное имя метода.

Переход `otherwise=True` является резервной ветвью одной группы `(source, event)`. Runtime вычисляет каждый обычный Guard ровно один раз: единственный истинный Guard выбирает свою ветвь, несколько истинных дают `AmbiguousTransitionError`, а при всех ложных выбирается `otherwise`. Сочетание `guard` и `otherwise` в одном переходе запрещено. Условная группа без резервной ветви компилируется с `MissingOtherwiseWarning`: в строгом режиме все ложные Guard приводят к `NoTransitionError`, в нестрогом — к диагностическому `IGNORED`.

Требуемая команда указывается в `@action(emit=...)`, а Runtime внедряет временный `Emit`. Вызов `emit(...)` не требует повторно указывать команду или `ctx`. Для нескольких команд применяется `@action(emits=(draw, log))` и вызов `emits[self.draw](...)`.

Синхронные запросы объявляются так же явно:

```python
@required_query(text="прочитать значение датчика")
def sensor_value(self) -> int:
    ...

@guard(query=sensor_value, text="значение превышает порог")
def above_threshold(
    self,
    ctx: ControllerContext,
    threshold: int,
    query: Query,
) -> bool:
    return query() > threshold
```

Для нескольких операций применяется `queries=(sensor_value, sensor_ready)` и параметр `queries: Queries`; конкретный запрос вызывается как `queries[self.sensor_value]()`. Query выполняется немедленно через настроенный `Connection`, не попадает в FIFO и не кэшируется. Capability нельзя сохранять для последующего использования. Контекст не содержит ссылку на Runtime и не предоставляет методов управления очередью. Полный небольшой пример расположен в [`examples/query_di.py`](../../examples/query_di.py).

Исполняемый пример разделён по ответственности: автоматные классы находятся в [`examples/array_sum/automatos`](../../examples/array_sum/automatos), сборка объектов и соединений — в [`examples/array_sum/program.py`](../../examples/array_sum/program.py), а headless-запуск — в [`examples/array_sum/array_sum.py`](../../examples/array_sum/array_sum.py). Headless-сценарий печатает не только результат, но и последовательную трассу операций, переходов и отправленных сообщений.

В актуальном примере Controller находится в `running`, пока ожидает пользовательский `tick`. Обычный Guard проверяет только наличие текущего элемента: при успехе элемент прибавляется к сумме и Controller переходит в `publishing`; когда Guard ложен, ветвь `otherwise` переводит его прямо в `done`. В состоянии `publishing` он ожидает команду `draw_completed` от View. View посылает её после применения снимка, поэтому возврат в `running` происходит через FIFO автоматически и не требует второго нажатия кнопки.

`StepResult.transition` и `TraceEvent.transition` содержат имя выбранного class-атрибута перехода. До выбора ветви, для пустого шага и `IGNORED` используется `None`; если исключение возникло внутри Action, имя уже выбранной ветви сохраняется.

Tkinter-пример при запуске сначала показывает настоящее начальное состояние `idle`. Кнопка `Init` отправляет команду `start`; после перехода в `running` она исчезает, а на её месте появляется кнопка «Следующий шаг», отправляющая пользовательскую команду `tick`. Общий адаптер событий находится в `ciao.visualization`, а конкретное представление этого примера — в `examples.array_sum.ui`.

## Экспорт в draw.io

Экспортер принимает уже объявленный `Program`; вручную дублировать состояния или связи не требуется:

```python
from ciao.visualization.drawio import export_program_drawio
from examples.array_sum.program import build_sample

sample = build_sample()
path = export_program_drawio(sample.program, "sum_program.drawio")
print(path)
```

Каталог назначения должен существовать. Повторный вызов атомарно заменяет прежний файл. Операция `start`, объявленная через `@provided_command(external=True)`, отображается внешним lollipop над блоком и соединяется с начальным состоянием. Видимые команды подписываются без типов и служебных `self`/`ctx`, например `start(values)`, `tick()` и `reset()`.

Операции из `Program.connections` отображаются в промежутке между автоматами как socket+ball: половина required завершается `halfCircle`, половина provided — `oval`, а над общим узлом остаётся только имя операции. В примере видны подписи `draw` и `draw_completed`. Полные сигнатуры операций остаются в `ciaoSignature`. Несколько связей между одной парой блоков выходят из разных точек и используют разнесённые полосы.

На стрелке перехода provided-событие показывается компактной сигнатурой. Для `@guard(text="...")` и обычного `@action(text="...")` добавляется `name: text`; имя action выделяется жирным. Запросы Guard/Action образуют отдельный блок `<<Query>>:` с одной сигнатурой на строку и сохраняются в метаданных `ciaoQueries`. Ветка `otherwise` показывается как `[else]`, получает метаданные `ciaoOtherwise=true` и располагается после Guard-ветвей. Если action содержит `emit`/`emits`, его собственные имя и `text` опускаются, а сигнатуры исходящих required-команд показываются в порядке кортежа. Каждый action и каждая emit-команда начинаются с новой строки, а `/` ставится только перед первой строкой общего блока действий. Внутри самой записи генератор переносов не добавляет. Размер редактируемого текстового поля рассчитывается по содержимому, а ближайшая свободная позиция выбирается с небольшим зазором от стрелки.

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
.\.venv\Scripts\python.exe -m examples.array_sum.array_sum
.\.venv\Scripts\python.exe examples\query_di.py
.\.venv\Scripts\python.exe -m examples.array_sum.array_sum_tk
.\.venv\Scripts\python.exe examples\export_drawio.py
```
