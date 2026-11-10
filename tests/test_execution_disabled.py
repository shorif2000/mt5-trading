import pytest

from trading.execution.order_gateway import ExecutionDisabled, OrderGateway
from trading.proposals.approval import ApprovalNotAvailable, request_approval


def test_order_submission_is_disabled():
    with pytest.raises(ExecutionDisabled):
        OrderGateway().submit({"symbol": "EURUSD"})


def test_approval_is_not_implemented():
    with pytest.raises(ApprovalNotAvailable):
        request_approval({"symbol": "EURUSD"})
