from datetime import date, timedelta

import pandas as pd
import pytest

from app.services.csv_parser import CsvFormatError, parse_and_validate
from app.services.seed_generator import SEED_MATERIALS, generate_seed_frame
from app.services.preprocessing import build_daily_series, classify_demand

TODAY = date(2026, 11, 1)


def test_valid_and_invalid_rows_reported_row_by_row():
    csv = (
        "material_name,date,quantity_consumed,current_stock\n"
        "Iron Ore,2026-05-01,820,5000\n"        # row 2 ok
        ",2026-05-02,100,\n"                    # row 3 missing name
        "Scrap,not-a-date,10,\n"                # row 4 bad date
        "Scrap,2026-05-03,-4,\n"                # row 5 bad quantity
        "Scrap,2026-05-03,abc,\n"               # row 6 bad quantity
        "Scrap,2030-01-01,10,\n"                # row 7 future
        "Limestone,02/05/2026,\"1,200\",\n"     # row 8 ok (dd/mm, thousands separator)
    ).encode()
    p = parse_and_validate(csv, TODAY)
    assert p.total_rows == 7 and p.invalid_rows == 5 and len(p.valid) == 2
    rows = {e["row"]: e["error"] for e in p.errors}
    assert "material_name" in rows[3] and "date" in rows[4].lower() and "greater than 0" in rows[5]
    assert "number" in rows[6] and "future" in rows[7].lower()
    assert p.valid.iloc[1]["quantity_consumed"] == 1200 and p.valid.iloc[1]["date"] == date(2026, 5, 2)
    assert p.valid.iloc[0]["current_stock"] == 5000


def test_missing_required_columns_and_empty_file():
    with pytest.raises(CsvFormatError, match="Missing required column"):
        parse_and_validate(b"material,qty\nIron Ore,5\n", TODAY)
    with pytest.raises(CsvFormatError):
        parse_and_validate(b"", TODAY)


def test_semicolon_delimiter_and_bom():
    p = parse_and_validate("\ufeffmaterial_name;date;quantity_consumed\nScrap;2026-05-01;5\n".encode("utf-8"), TODAY)
    assert len(p.valid) == 1


def test_seed_data_generation():
    end = date(2026, 10, 30)
    df = generate_seed_frame(end, 18, 42)
    assert set(df["material_id"]) == {m["material_id"] for m in SEED_MATERIALS} and len(SEED_MATERIALS) == 5
    assert (df["quantity_consumed"] > 0).all() and df["date"].max() == end
    span = (pd.Timestamp(end) - pd.Timestamp(df["date"].min())).days
    assert 540 <= span <= 550  # ~18 months of daily data
    assert generate_seed_frame(end, 18, 42).equals(df)  # deterministic

    profiles = {}
    for m in SEED_MATERIALS:
        r = df[df.material_id == m["material_id"]][["date", "quantity_consumed"]]
        s = build_daily_series(r, end)
        profiles[m["name"]] = classify_demand(s["adjusted"], s["quantity"])
    assert profiles["Iron Ore"].label == "SEASONAL"
    assert profiles["Coking Coal"].trend_direction == "UP" and profiles["Dolomite"].trend_direction == "DOWN"
    assert len({m["current_stock"] / m["base"] for m in SEED_MATERIALS}) == 5  # different stock cover per material
