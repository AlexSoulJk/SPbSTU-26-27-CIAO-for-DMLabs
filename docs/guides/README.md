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

Исполняемый пример разделён по ответственности: автоматные классы находятся в [`examples/array_sum/automatos`](../../examples/array_sum/automatos), Window — в [`examples/array_sum/ui`](../../examples/array_sum/ui), общие DTO — в `contracts.py`, а сборка объектов и соединений — в [`examples/array_sum/program.py`](../../examples/array_sum/program.py). `headless_run.py` и `interactive_run.py` запускают одну и ту же программу.

Controller различает `running_step` и `running_all`. Каждый `tick` обрабатывает ровно один элемент. Пошаговый режим публикует промежуточные снимки, автоматический планирует следующий `tick` через self-connection и публикует только итог. Последний вычислительный тик сразу создаёт `COMPLETED`, поэтому дополнительного пустого тика нет. View подтверждает каждый опубликованный снимок командой `draw_completed`; `reset` обнуляет прогресс, сохраняет входной массив и возвращает оба автомата в `idle`, а явный `finish` переводит их в финальные состояния.

`StepResult.transition` и `TraceEvent.transition` содержат имя выбранного class-атрибута перехода. До выбора ветви, для пустого шага и `IGNORED` используется `None`; если исключение возникло внутри Action, имя уже выбранной ветви сохраняется.

Tkinter-пример при запуске показывает начальное состояние `idle`. Кнопка `Init` отправляет `StartInput` в View, а View уже маршрутизирует `start` Controller. В пошаговом режиме появляется кнопка «Следующий шаг»; в автоматическом Controller продвигается сам. Window не читает Runtime snapshot: данные, кнопки и статус приходят отдельными external required-командами View.

## Экспорт в draw.io

Экспортер принимает уже объявленный `Program`; вручную дублировать состояния или связи не требуется:

```python
from ciao.visualization.drawio import export_program_drawio
from examples.array_sum.program import build_sample

sample = build_sample()
path = export_program_drawio(sample.program, "sum_program.drawio")
print(path)
```

Каталог назначения должен существовать. Повторный вызов атомарно заменяет прежний файл. External provided-команды View отображаются lollipop, external required-команды — фиксированной ножкой с подковой. Их подписи находятся над символами и участвуют в детерминированном расчёте горизонтальных зазоров. Начало автомата показано отдельной чёрной точкой Entry, final-состояние — Exit с подписью.

Операции из `Program.connections` отображаются в промежутке между автоматами как socket+ball: половина required завершается `halfCircle`, половина provided — `oval`, а над общим узлом остаётся только имя операции. В примере видны подписи `draw` и `draw_completed`. Полные сигнатуры операций остаются в `ciaoSignature`. Query endpoint получает пометку `«query»`, а обе половины Query connection и её подпись окрашиваются в красный без добавления стрелки направления. Несколько связей между одной парой блоков выходят из разных точек и используют разнесённые полосы.

На стрелке перехода provided-событие показывается компактной сигнатурой. Для `@guard(text="...")` и обычного `@action(text="...")` добавляется `name: text`; имя action выделяется жирным. Запросы Guard/Action образуют визуально отделённый красный блок `<<Query>>:` с одной сигнатурой на строку и сохраняются в метаданных `ciaoQueries`. Ветка `otherwise` показывается как `[else]`, получает метаданные `ciaoOtherwise=true` и располагается после Guard-ветвей. Если action содержит `emit`/`emits`, его собственные имя и `text` опускаются, а сигнатуры исходящих required-команд показываются в порядке кортежа. Каждый action и каждая emit-команда начинаются с новой строки, а `/` ставится только перед первой строкой общего блока действий. Внутри самой записи генератор переносов не добавляет. Размер редактируемого текстового поля рассчитывается по содержимому, а ближайшая свободная позиция выбирается с небольшим зазором от достаточно длинного участка стрелки. Action без `emit`/`emits` получает на нижней границе блока компактную текстовую декларацию с именем и стоящий сразу после неё UML required-interface в виде короткой перпендикулярной линии с полудугой. Полная сигнатура и `text` остаются в XML-метаданных подписи.

Фон области автомата остаётся белым. Цвет роли применяется к обычным состояниям и переходам: голубой для `Controller`, зелёный для `View`. До назначения координат экспортёр измеряет все подписи, затем разносит обычные и конечные состояния, Decision и маршруты переходов. Поэтому длинный текст участвует в размере рамки, стрелки не должны проходить через посторонние вершины, а нижние интерфейсы добавляются только после расчёта графа. Порядок объектов совпадает с `Program.objects`, а семантические XML ID не зависят от вставки несвязанных деклараций.

Скрипт [`examples/export_drawio.py`](../../examples/export_drawio.py) создаёт только редактируемые `.drawio` для array sum, Query DI и calculator в `examples/schemas/generated_drawio/`. Библиотеки фигур из `examples/schemas` экспортёр не читает и не изменяет; PNG и внешний renderer не требуются.

### Сравнение стратегий компоновки

Baseline и экспериментальный многофазный layout можно сравнить на одних и тех
же штатных примерах без дополнительных зависимостей:

```powershell
.\.venv\Scripts\python.exe -m examples.benchmark_drawio_layouts
```

Таблица показывает размер страницы, общий штраф, перекрытия объектов, долю стрелок внутри
посторонних объектов, долю наложения стрелок друг на друга, число пересечений
edge-label со стрелками и среднее расстояние подписи до собственного перехода.
Меньшие значения лучше. Процент `improvement` положителен, когда multiphase
уменьшил общий штраф относительно baseline.

Для третьей стратегии на ELK Layered один раз установите закреплённый `elkjs`
и добавьте флаг `--elk`:

```powershell
npm install
.\.venv\Scripts\python.exe -m examples.benchmark_drawio_layouts --elk
```

ELK выполняет два прохода: сначала по внутренним графам автоматов, затем по
графу самих автоматных блоков и assembly-connections. Основной Python-пакет не
импортирует JavaScript-зависимость; без `--elk` benchmark и публичный экспорт
работают только на Python.

Если автомат содержит не меньше четырёх состояний и подпись хотя бы одного
перехода имеет ширину от 320 px, ELK-стратегия использует плотный профиль: граф
располагается под context-card, длинные пояснения на переходах скрываются из
рисунка, а аргументы вызовов показываются как `…`. Полный исходный текст
остаётся в атрибуте `ciaoFullLabel`; подписи Action и интерфейсов на границе
автомата не сокращаются.

Во всех стратегиях имя автоматного объекта и класса остаётся первой строкой
цветной context-card в левом верхнем углу автомата. Отдельной полосы заголовка
нет. Нижние Action-подписи сопровождаются UML required-interface в виде короткой
перпендикулярной линии с полудугой; provided-операции используют lollipop. Эту
полосу раскладывает не ELK, а общий детерминированный код: каждая пара имеет вид
«значок, зазор, подпись», после чего начинается следующая пара. Required-ярлык
состоит из перпендикулярной ножки длиной 24 px и фиксированной подковы на её
конце; размеры не зависят от высоты автомата.

Для машинной обработки используется `--json`. Чтобы одновременно получить
редактируемые диаграммы обеих стратегий, передайте каталог через
`--output-dir`, например:

```powershell
.\.venv\Scripts\python.exe -m examples.benchmark_drawio_layouts `
    array_sum calculator --output-dir .\layout-benchmark
```

Обычный `export_program_drawio()` пока не переключён на новую стратегию и
продолжает создавать baseline: benchmark не меняет пользовательский экспорт.

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
.\.venv\Scripts\python.exe -m examples.array_sum.headless_run
.\.venv\Scripts\python.exe examples\query_di.py
.\.venv\Scripts\python.exe -m examples.array_sum.interactive_run
.\.venv\Scripts\python.exe examples\export_drawio.py
.\.venv\Scripts\python.exe -m examples.benchmark_drawio_layouts
npm install
.\.venv\Scripts\python.exe -m examples.benchmark_drawio_layouts --elk
```
