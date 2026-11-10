"""Read-only reconciliation helpers for comparing expected and observed records."""


def compare_order_status(expected_status: str, observed_status: str) -> bool:
    """Return whether two externally supplied statuses match exactly."""
    return expected_status == observed_status
