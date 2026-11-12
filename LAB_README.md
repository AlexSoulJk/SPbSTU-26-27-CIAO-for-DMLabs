# Оформление лабораторных примеров CIAO

Каждый законченный пример оформляется как самостоятельный Python-пакет в
`examples/<example_name>`. Пример должен показывать стандартное разделение
декларативной модели, сборки программы и необязательного UI, а не хранить рядом
несколько поколений одной реализации.

## Рекомендуемая структура

```text
examples/<example_name>/
    __init__.py          # компактные экспорты предметных типов примера
    contracts.py         # общие DTO Controller/View/Window
    automatos/
        __init__.py
        controller.py    # Controller и его AutomatonContext
        view.py          # View и его AutomatonContext
    ui/
        __init__.py
        window.py        # конкретный Window без доступа к Runtime
    program.py           # AutomatonObject, Connection и единый build_sample()
    headless_run.py      # необязательный запуск без GUI
    interactive_run.py   # wiring Runtime, UIConnection и Window
```

Имена файлов автоматов можно уточнять предметным префиксом, например
`sum_controller.py`, если в пакете потенциально несколько Controller. При этом
внутри одного примера остаётся одна актуальная сборка `Program`.

## Границы ответственности

- `automatos` не импортирует Runtime, Tkinter или инфраструктуру подключения;
- `ui` не получает Runtime и не читает snapshot автоматных объектов;
- `program.py` не создаёт Window и не регистрирует UI-handlers;
- `interactive_run.py` содержит только конфигурацию запуска и bindings;
- `headless_run.py` отправляет те же типизированные DTO напрямую в Runtime;
- старую реализацию после замены не следует сохранять во вложенной подпапке
  вроде `legacy`, `interactive` или `new`; историю хранит Git.

## Эталон: ArraySum

```powershell
.venv\Scripts\python -m examples.array_sum.headless_run
.venv\Scripts\python -m examples.array_sum.interactive_run
```

Его редактируемая ELK-диаграмма создаётся общей точкой экспорта:

```powershell
.venv\Scripts\python examples\export_drawio.py
```
