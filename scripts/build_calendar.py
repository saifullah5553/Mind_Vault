"""Build (and print) the rolling content calendar.

Usage:
    python -m scripts.build_calendar
    python -m scripts.build_calendar --days 30
"""

from __future__ import annotations

import argparse

from core.calendar import build_calendar


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Mind_Vault content calendar")
    parser.add_argument("--days", type=int, default=None, help="horizon in days (default from config)")
    args = parser.parse_args()

    cal = build_calendar(days=args.days)
    print(f"\n{len(cal)} scheduled slots (saved to storage/calendar.json)\n")
    for e in cal[:20]:
        print(f"  {e['date']} {e['weekday']}  {e['format']:<5} {e['category']:<10} {e['subcategory']}")
    if len(cal) > 20:
        print(f"  … and {len(cal) - 20} more")
    print()


if __name__ == "__main__":
    main()
