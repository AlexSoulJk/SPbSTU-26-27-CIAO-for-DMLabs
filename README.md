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
.venv\Scripts\python examples\array_sum.py
```

## Tkinter-пример

```powershell
.venv\Scripts\python examples\array_sum_tk.py
```

## Экспорт диаграммы draw.io

```powershell
.venv\Scripts\python examples\export_drawio.py
```

Команда создаёт `examples/sum_program.drawio` из фактической декларации `Program`. Файл состоит из нативных редактируемых фигур diagrams.net.

## Реализовано

- декларативные `State`, включая `final=True`, операции, `Guard`, `Action` и `Transition`; `@guard`/`@action` поддерживают необязательный `text` для понятных подписей диаграммы;
- явные исходящие required-команды `Action` через `@action(emit=...)` / `@action(emits=(...))` и временные `Emit` / `Emits`;
- типизированные контексты и роли `Automaton`, `ControllerAutomaton`, `ViewAutomaton`;
- компиляция и валидация `Program`/`Connection`;
- FIFO-runtime, синхронные запросы, трасса и снимки состояния;
- строгий/нестрогий режим и ограничение `run()`;
- общий Tkinter-адаптер событий через `after` и отдельное представление примера суммы массива;
- односторонний экспорт `Program → .drawio` с состояниями, переходами, интерфейсами и `Connection`.

Цельный код декларации двух автоматов находится в `examples/test_mock_sample.py`. Архитектурные документы и руководства расположены в `docs/`.
