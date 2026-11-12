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

## Headless-пример

```powershell
.venv\Scripts\python -m examples.array_sum.array_sum
```

Помимо результата команда печатает последовательную трассу операций runtime:
переходы состояний и созданные ими сообщения `emit`.

## Tkinter-пример

```powershell
.venv\Scripts\python -m examples.array_sum.array_sum_tk
```

Интерактивный пример поддерживает пошаговый и автоматический режимы. События
кнопок поступают в автомат View через `TkConnection`, а Window не читает
состояние Runtime: данные, органы управления и статус обновляются отдельными
типизированными presentation-командами.

## Экспорт диаграммы draw.io

```powershell
.venv\Scripts\python examples\export_drawio.py
```

Команда использует ELK Layered и создаёт набор схем из фактических деклараций
`Program` в
`examples/schemas/generated_drawio`, включая новый
`interactive_sum_program.drawio`. Для запуска необходимы Node.js и зависимости
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

Старый пример в `examples/array_sum/automatos` и `program.py` сохранён как
baseline для диаграмм. Интерактивный Controller/View/Window расположен в
`examples/array_sum/interactive`; `array_sum_tk.py` является его GUI-точкой
запуска, а `array_sum.py` сохраняет простой headless-запуск baseline.
Архитектурные документы и руководства расположены в `docs/`.
