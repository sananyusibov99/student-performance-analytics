"""Describe every CSV in data/model as {table: [[column, tom_type], ...]} for build-star-model.ps1.

Usage: py -3.13 -I make_model_spec.py <model dir> <spec.json>
"""
import json
import sys
from pathlib import Path

import pandas as pd

DATE_COLUMNS = {"date", "birth_date", "start_date", "end_date", "enrollment_date", "hire_date"}


def tom_type(name, series):
    if name.endswith("_key") or name in {"days_late", "cohort_year", "grade_level_num"}:
        return "Int64"
    if name in DATE_COLUMNS:
        return "DateTime"
    if pd.api.types.is_bool_dtype(series):
        return "Boolean"
    if pd.api.types.is_integer_dtype(series):
        return "Int64"
    if pd.api.types.is_float_dtype(series):
        non_null = series.dropna()
        return "Int64" if len(non_null) and (non_null % 1 == 0).all() and name not in {"score", "points_earned", "cost_usd", "final_score", "grade_points", "entry_gpa"} else "Double"
    return "String"


def main():
    model_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    spec = {}
    for f in sorted(model_dir.glob("*.csv")):
        df = pd.read_csv(f)
        spec[f.stem] = [[c, tom_type(c, df[c])] for c in df.columns]
    out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    for t, cols in spec.items():
        print(t, " ".join(f"{c}:{ty[0]}" for c, ty in cols))


if __name__ == "__main__":
    main()
