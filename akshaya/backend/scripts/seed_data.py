"""Seed the database with 18 months of realistic demo consumption and compute forecasts.

Usage (from the backend folder):
    python scripts/seed_data.py            # 18 months
    python scripts/seed_data.py --months 12
    python scripts/seed_data.py --csv demo.csv   # also write the data as an uploadable CSV

WARNING: replaces all existing consumption data, forecasts and snapshots.
"""
import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import today  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.services.demo import seed_database  # noqa: E402
from app.services.seed_generator import SEED_MATERIALS, generate_seed_frame  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", type=int, default=18)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--csv", help="also export the generated data in the upload format")
    args = ap.parse_args()

    init_db()
    with SessionLocal() as db:
        res = seed_database(db, months=args.months, rng_seed=args.seed)
    print(f"Inserted {res['records_inserted']} records ({res['start_date']} -> {res['end_date']})")
    print(f"{'material':<18}{'class':<13}{'model':<20}{'status':<26}cover(d)")
    for m in res["materials"]:
        print(f"{m['material_id']:<18}{m['demand_class']:<13}{m['model']:<20}{m['stock_status']:<26}{m['days_of_cover']}")
    for f in res["failed"]:
        print("FAILED:", f)

    if args.csv:
        df = generate_seed_frame(today() - timedelta(days=1), args.months, args.seed)
        meta = {m["material_id"]: m for m in SEED_MATERIALS}
        df["material_name"] = df["material_id"].map(lambda i: meta[i]["name"])
        df["unit"] = "tonne"
        df[["material_name", "date", "quantity_consumed", "unit"]].to_csv(args.csv, index=False)
        print("Wrote", args.csv)


if __name__ == "__main__":
    main()
