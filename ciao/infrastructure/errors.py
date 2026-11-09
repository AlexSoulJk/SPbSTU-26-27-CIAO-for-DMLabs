"""Диагностируемые ошибки модели и исполнения CIAO."""


class CiaoError(Exception):
    """Базовая ошибка библиотеки."""


class ModelValidationError(CiaoError):
    """Декларативная модель противоречит контракту MVP."""


class MissingOtherwiseWarning(UserWarning):
    """Условная группа переходов не содержит резервную ветвь."""


class RuntimeExecutionError(CiaoError):
    """Ошибка во время исполнения скомпилированной модели."""


class NoTransitionError(RuntimeExecutionError):
    """Для сообщения не найден применимый переход."""


class AmbiguousTransitionError(RuntimeExecutionError):
    """Для сообщения одновременно применимы несколько переходов."""


class GuardExecutionError(RuntimeExecutionError):
    """Пользовательское условие завершилось исключением."""


class ActionExecutionError(RuntimeExecutionError):
    """Пользовательское действие завершилось исключением."""


class InvalidRuntimeCallError(RuntimeExecutionError):
    """Пользователь вызвал runtime-операцию в недопустимой фазе."""


class QueryRoutingError(RuntimeExecutionError):
    """Синхронный запрос нельзя однозначно маршрутизировать."""


class QueryExecutionError(RuntimeExecutionError):
    """Пользовательская реализация provided-query завершилась исключением."""


class StepLimitExceeded(RuntimeExecutionError):
    """Исполнение достигло настроенного предела шагов."""
