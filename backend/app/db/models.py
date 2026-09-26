from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Float,
    UniqueConstraint
)

from app.db.database import Base


class StockPrice(Base):

    __tablename__ = "stock_prices"

    id = Column(Integer, primary_key=True)

    symbol = Column(String(50), nullable=False)

    timestamp = Column(DateTime, nullable=False)

    open = Column(Float, nullable=False)

    high = Column(Float, nullable=False)

    low = Column(Float, nullable=False)

    close = Column(Float, nullable=False)

    # Split/dividend-adjusted close; use this for returns and ML labels
    adj_close = Column(Float, nullable=True)

    volume = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timestamp",
            name="uq_stock_timestamp"
        ),
    )