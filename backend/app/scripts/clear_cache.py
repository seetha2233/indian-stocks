"""Invalidate the API cache after running a pipeline step by hand.

refresh does this automatically after every step.

Usage (from backend/):
    python -m app.scripts.clear_cache
"""

from app.core.cache import bump_data_version


def main() -> None:
    print(f"API cache invalidated (data version {bump_data_version()})")


if __name__ == "__main__":
    main()
