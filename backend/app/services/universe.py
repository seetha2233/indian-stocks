from io import StringIO
from pathlib import Path

import pandas as pd
import requests


NIFTY100_URL = (
    "https://archives.nseindia.com/content/indices/ind_nifty100list.csv"
)

# Snapshot kept in the repo so runs are reproducible
NIFTY100_CSV = (
    Path(__file__).resolve().parents[3] / "data" / "universe" / "nifty100.csv"
)


def refresh_nifty100() -> pd.DataFrame:
    """Download the current NIFTY 100 constituents from NSE."""

    response = requests.get(
        NIFTY100_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20
    )

    response.raise_for_status()

    df = pd.read_csv(StringIO(response.text))

    if "Symbol" not in df.columns or len(df) < 90:
        raise ValueError("Unexpected NIFTY 100 file from NSE")

    NIFTY100_CSV.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(NIFTY100_CSV, index=False)

    return df


def load_nifty100() -> list[str]:
    """NSE symbols (without .NS) from the local snapshot."""

    df = pd.read_csv(NIFTY100_CSV)

    return df["Symbol"].str.strip().tolist()


# --- All NSE main-board equities -------------------------------------------

NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

NSE_EQUITY_CSV = NIFTY100_CSV.parent / "nse_equity.csv"

# EQ = normal trading, BE = trade-for-trade (listed, restricted).
# BZ (non-compliant, often suspended) is left out.
NSE_SERIES = ("EQ", "BE")

UNIVERSES = ("nse", "nifty100")


def _read_nse(text_or_path) -> pd.DataFrame:

    df = pd.read_csv(text_or_path)
    df.columns = [c.strip() for c in df.columns]

    return df


def refresh_nse_equities() -> pd.DataFrame:
    """Download NSE's list of listed equities (main board)."""

    response = requests.get(
        NSE_EQUITY_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30
    )

    response.raise_for_status()

    df = _read_nse(StringIO(response.text))

    if "SYMBOL" not in df.columns or len(df) < 1000:
        raise ValueError("Unexpected equity list from NSE")

    NSE_EQUITY_CSV.parent.mkdir(parents=True, exist_ok=True)
    NSE_EQUITY_CSV.write_text(response.text)

    return df


def load_nse_equities() -> list[str]:
    """NSE symbols (without .NS) in the tradable series."""

    df = _read_nse(NSE_EQUITY_CSV)
    df = df[df["SERIES"].str.strip().isin(NSE_SERIES)]

    return df["SYMBOL"].str.strip().tolist()


def load_universe(name: str) -> list[str]:

    if name == "nse":
        return load_nse_equities()
    if name == "nifty100":
        return load_nifty100()

    raise ValueError(f"universe must be one of {UNIVERSES}, got {name!r}")


def refresh_universe(name: str) -> int:

    return len(refresh_nse_equities() if name == "nse" else refresh_nifty100())


def refresh_lists(strict: bool = False) -> list[str]:
    """Re-download both stock lists, falling back to the local snapshots.

    Both are needed whatever the universe: the NSE list names every stock
    and the NIFTY 100 list sets each card's nifty100 flag. A download that
    fails or looks wrong leaves the snapshot untouched; with strict=True
    it raises instead. Returns one status line per list.
    """

    lines = []

    for name, path in (("nse", NSE_EQUITY_CSV), ("nifty100", NIFTY100_CSV)):

        old = set(load_universe(name)) if path.exists() else set()

        try:
            refresh_universe(name)
        except Exception as e:
            if strict or not path.exists():
                raise
            lines.append(
                f"{name}: download failed ({type(e).__name__}: {e}); "
                f"using the snapshot from {pd.Timestamp(path.stat().st_mtime, unit='s'):%Y-%m-%d}"
            )
            continue

        new = set(load_universe(name))
        added, removed = sorted(new - old), sorted(old - new)

        lines.append(
            f"{name}: {len(new)} stocks, {len(added)} added, {len(removed)} removed"
            + (f" (new: {', '.join(added[:8])})" if 0 < len(added) < len(new) else "")
        )

    return lines


def universe_table(name: str) -> pd.DataFrame:
    """symbol (with .NS) and company name for a universe."""

    if name == "nse":
        df = _read_nse(NSE_EQUITY_CSV)
        df = df[df["SERIES"].str.strip().isin(NSE_SERIES)]
        out = pd.DataFrame({"symbol": df["SYMBOL"].str.strip(), "long_name": df["NAME OF COMPANY"].str.strip()})
    elif name == "nifty100":
        df = pd.read_csv(NIFTY100_CSV)
        out = pd.DataFrame({"symbol": df["Symbol"].str.strip(), "long_name": df["Company Name"].str.strip()})
    else:
        raise ValueError(f"universe must be one of {UNIVERSES}, got {name!r}")

    out["symbol"] = out["symbol"] + ".NS"

    return out.reset_index(drop=True)
