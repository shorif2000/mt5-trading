"""No approval or execution mechanism is implemented in read-only version."""


class ApprovalNotAvailable(RuntimeError):
    pass


def request_approval(*_args, **_kwargs) -> None:
    raise ApprovalNotAvailable(
        "Approval and execution are not implemented. This project is read-only."
    )
