# CIAO для лабораторных работ

Учебный Python-фреймворк для декларативного описания и пошагового исполнения взаимодействующих автоматных объектов CIAO.

## Требования

- Python 3.11 или новее.

## Установка для разработки

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Запуск тестов

```powershell
.venv\Scripts\python -m pytest
```

## Headless-примеры

```powershell
.venv\Scripts\python -m examples.array_sum.headless_run
.venv\Scripts\python -m examples.calculator.headless_run
```

Помимо результата команда печатает последовательную трассу операций runtime:
переходы состояний и созданные ими сообщения `emit`.

## Tkinter-примеры

```powershell
.venv\Scripts\python -m examples.array_sum.interactive_run
.venv\Scripts\python -m examples.calculator.interactive_run
```

ArraySum поддерживает пошаговый и автоматический режимы, Calculator показывает
преобразование в ОПН и вычисление по одному токену. В обоих примерах события
кнопок поступают в автомат View через `TkConnection`, а Window не читает
состояние Runtime: данные, органы управления и статус обновляются отдельными
типизированными presentation-командами.

## Экспорт диаграммы draw.io

```powershell
.venv\Scripts\python examples\export_drawio.py
```

Команда использует ELK Layered и создаёт набор схем из фактических деклараций
`Program` в
`examples/schemas/generated_drawio`, включая актуальный `sum_program.drawio`.
Для запуска необходимы Node.js и зависимости
из `package.json` (`npm install`). Публичный `export_program_drawio(...)`
сохраняет baseline по умолчанию, а альтернативная стратегия передаётся явно
через keyword-only параметр `layout_builder`.

## Реализовано

- декларативные `State`, включая `final=True`, операции, `Guard`, `Action` и `Transition`; переходы поддерживают явную резервную ветвь `otherwise=True`, а `@guard`/`@action` — необязательный `text` для диаграммы;
- явные исходящие required-команды `Action` через `@action(emit=...)` / `@action(emits=(...))` и временные `Emit` / `Emits`;
- типизированные контексты и роли `Automaton`, `ControllerAutomaton`, `ViewAutomaton`;
- компиляция и валидация `Program`/`Connection`, включая группы Guard/otherwise и `MissingOtherwiseWarning`;
- FIFO-runtime, синхронные запросы, трасса с именем выбранного перехода и снимки состояния;
- строгий/нестрогий режим и ограничение `run()`;
- общий `TkConnection` с пошаговым `after`-pump, типизированными источниками
  payload и external-командами для обновления Window;
- односторонний экспорт `Program → .drawio` с состояниями, переходами, интерфейсами и `Connection`.

Примеры ArraySum и Calculator разделены на `automatos`, `ui`, общие DTO в
`contracts.py` и единую сборку в `program.py`. Точки запуска называются
`headless_run.py` и `interactive_run.py`; правила оформления остальных
лабораторных примеров зафиксированы в `LAB_README.md`.
Архитектурные документы и руководства расположены в `docs/`.
