"""No approval or execution mechanism is implemented in read-only version."""

from typing import NoReturn


class ApprovalNotAvailable(RuntimeError):
    pass


def request_approval(*_args: object, **_kwargs: object) -> NoReturn:
    raise ApprovalNotAvailable(
        "Approval and execution are not implemented. This project is read-only."
    )
