from sqlalchemy import text

from app.db.database import Base, engine
from app.db import models  # noqa: F401  (registers tables on Base)


def init_db() -> None:

    Base.metadata.create_all(bind=engine)

    # create_all does not add columns to an existing table
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE stock_prices "
                "ADD COLUMN IF NOT EXISTS adj_close DOUBLE PRECISION"
            )
        )
