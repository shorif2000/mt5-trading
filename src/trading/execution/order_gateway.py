"""Fail-closed execution boundary. Intentionally cannot submit orders."""

from typing import NoReturn


class ExecutionDisabled(RuntimeError):
    pass


class OrderGateway:
    def submit(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise ExecutionDisabled(
            "Order submission is disabled and not implemented in this project."
        )

    def modify(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise ExecutionDisabled("Order modification is disabled and not implemented.")

    def close(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise ExecutionDisabled("Position closing is disabled and not implemented.")
