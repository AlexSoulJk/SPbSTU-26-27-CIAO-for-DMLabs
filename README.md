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

## Экспорт диаграммы draw.io

```powershell
.venv\Scripts\python examples\export_drawio.py
```

Команда создаёт `examples/sum_program.drawio` из фактической декларации `Program`. Файл состоит из нативных редактируемых фигур diagrams.net.

## Реализовано

- декларативные `State`, включая `final=True`, операции, `Guard`, `Action` и `Transition`; переходы поддерживают явную резервную ветвь `otherwise=True`, а `@guard`/`@action` — необязательный `text` для диаграммы;
- явные исходящие required-команды `Action` через `@action(emit=...)` / `@action(emits=(...))` и временные `Emit` / `Emits`;
- типизированные контексты и роли `Automaton`, `ControllerAutomaton`, `ViewAutomaton`;
- компиляция и валидация `Program`/`Connection`, включая группы Guard/otherwise и `MissingOtherwiseWarning`;
- FIFO-runtime, синхронные запросы, трасса с именем выбранного перехода и снимки состояния;
- строгий/нестрогий режим и ограничение `run()`;
- общий Tkinter-адаптер событий через `after` и отдельное представление примера суммы массива;
- односторонний экспорт `Program → .drawio` с состояниями, переходами, интерфейсами и `Connection`.

Пример суммы разделён на автоматные классы в `examples/array_sum/automatos`,
сборку программы в `examples/array_sum/program.py`, предметный Tkinter-интерфейс
в `examples/array_sum/ui` и отдельные точки headless- и GUI-запуска.
Архитектурные документы и руководства расположены в `docs/`.
