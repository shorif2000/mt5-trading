"""A proposal is descriptive data, never an order."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from trading.models import Direction


class TradeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    symbol: str
    direction: Direction
    created_at: datetime
    market_data_timestamp: datetime
    timeframe: str
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    volume: float = Field(gt=0)
    estimated_loss_account_currency: float = Field(gt=0)
    estimated_margin_account_currency: float | None = None
    rationale: list[str]
    limitations: list[str]
    status: str = "research_only"
