import pandas as pd
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def _sql_type(series: pd.Series) -> str:

    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(series):
        return "BIGINT"
    if pd.api.types.is_float_dtype(series):
        return "DOUBLE PRECISION"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "TIMESTAMP"
    return "TEXT"


def replace_day(engine: Engine, table: str, df: pd.DataFrame) -> None:
    """Replace one day's rows in a per-day history table.

    Keeps other days. Columns new to the table are added (as nullable), so
    older days simply have NULL for them.
    """

    day = df["timestamp"].iloc[0]

    with engine.begin() as conn:

        insp = inspect(conn)

        if insp.has_table(table):

            existing = {c["name"] for c in insp.get_columns(table)}

            for col in df.columns.difference(list(existing)):
                conn.execute(
                    text(
                        f'ALTER TABLE {table} ADD COLUMN "{col}" '
                        f"{_sql_type(df[col])}"
                    )
                )

            conn.execute(
                text(f"DELETE FROM {table} WHERE timestamp = :ts"),
                {"ts": pd.Timestamp(day).to_pydatetime()}
            )

        df.to_sql(table, conn, if_exists="append", index=False)
