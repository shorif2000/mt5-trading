"""Fail-closed execution boundary. Intentionally cannot submit orders."""


class ExecutionDisabled(RuntimeError):
    pass


class OrderGateway:
    def submit(self, *_args, **_kwargs) -> None:
        raise ExecutionDisabled(
            "Order submission is disabled and not implemented in this project."
        )

    def modify(self, *_args, **_kwargs) -> None:
        raise ExecutionDisabled("Order modification is disabled and not implemented.")

    def close(self, *_args, **_kwargs) -> None:
        raise ExecutionDisabled("Position closing is disabled and not implemented.")
