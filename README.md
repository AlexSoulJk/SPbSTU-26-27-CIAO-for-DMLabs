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

## Реализовано

- декларативные `State`, операции, `Guard`, `Action` и `Transition`;
- типизированные контексты `Automaton[ContextT]`;
- компиляция и валидация `Program`/`Connection`;
- FIFO-runtime, синхронные запросы, трасса и снимки состояния;
- строгий/нестрогий режим и ограничение `run()`;
- необязательные Tkinter-виджеты и адаптер событий через `after`.

Цельный код декларации двух автоматов находится в `examples/test_mock_sample.py`. Архитектурные документы и руководства расположены в `docs/`.
