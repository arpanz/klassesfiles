"""
Roll number parser — generates rollno_{batch}.json from an Excel file.

Sheet layout (sheet names are detected by keyword, case-insensitive):
  - One sheet whose name contains "core"  → Roll Number | Section
    Section values are plain main sections, e.g. "IT-01", "CSE-05".
  - Zero or more sheets whose name contains "elective" or "pe"
    → Roll Number | Section
    Section values are in SUBJECT_SECTION format, e.g. "AI_IT-01"
    (subject=AI, elective section=IT-01). Sheets are taken in workbook
    order as E1, E2 (max 2 elective sheets).

Output format:
  No electives  → { "2306001": "IT-01" }           (flat string)
  With electives → { "2306001": ["IT-01", "AI_IT-01", "CC_CSE-01"] }

Merge mode (default): existing rolls not in the new file are kept.
Replace mode: output only contains rolls from the uploaded file.

Usage:
    python scripts/rollno_parser.py input.xlsx --batch 2023 --mode merge
    python scripts/rollno_parser.py input.xlsx --batch 2023 --mode replace
"""
import sys
import json
import argparse
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_sheet(xl: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    df = xl.parse(sheet_name)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def find_roll_col(df: pd.DataFrame) -> str:
    """Return the name of the roll-number column (case-insensitive match)."""
    for col in df.columns:
        if "roll" in col.lower():
            return col
    raise ValueError(f"No 'Roll' column found. Columns: {list(df.columns)}")


def find_section_col(df: pd.DataFrame) -> str:
    """Return the name of the section column."""
    for col in df.columns:
        if "section" in col.lower():
            return col
    raise ValueError(f"No 'Section' column found. Columns: {list(df.columns)}")


def parse_sheet(df: pd.DataFrame) -> dict:
    """Return {roll_str: section_str} from a sheet."""
    roll_col = find_roll_col(df)
    sec_col = find_section_col(df)
    result = {}
    for _, row in df.iterrows():
        roll = str(row[roll_col]).strip().replace(".0", "")  # handle float ints
        section = str(row[sec_col]).strip()
        if not roll or roll.lower() == "nan":
            continue
        if not section or section.lower() == "nan":
            continue
        result[roll] = section
    return result


def build_json(xl: pd.ExcelFile) -> dict:
    sheets = xl.sheet_names
    print(f"Sheets found: {sheets}")

    # Identify core and elective sheets by name keyword.
    core_sheet = None
    elective_sheets = []

    for name in sheets:
        nl = name.lower()
        if "core" in nl:
            core_sheet = name
        elif "elective" in nl or "pe" in nl:
            elective_sheets.append(name)

    if core_sheet is None:
        # Fallback: first sheet is core.
        core_sheet = sheets[0]
        print(f"Warning: no 'core' sheet found, using first sheet: '{core_sheet}'")

    elective_sheets = elective_sheets[:2]  # cap at E1 + E2
    print(f"Core sheet   : '{core_sheet}'")
    print(f"Elective sheets: {elective_sheets}")

    core_map = parse_sheet(load_sheet(xl, core_sheet))
    print(f"Parsed {len(core_map)} roll numbers from core sheet.")

    if not elective_sheets:
        # No electives — flat string format.
        return core_map

    # With electives — list format.
    elec_maps = []
    for sheet in elective_sheets:
        m = parse_sheet(load_sheet(xl, sheet))
        elec_maps.append(m)
        print(f"Parsed {len(m)} entries from elective sheet '{sheet}'.")

    result = {}
    all_rolls = set(core_map.keys())
    for m in elec_maps:
        all_rolls.update(m.keys())

    for roll in all_rolls:
        main = core_map.get(roll)
        if main is None:
            print(f"Warning: roll {roll} found in elective sheet but not core; skipping.")
            continue
        entry = [main]
        for m in elec_maps:
            if roll in m:
                entry.append(m[roll])
        # Only use list format if at least one elective was found.
        result[roll] = entry if len(entry) > 1 else main

    return result


def main():
    ap = argparse.ArgumentParser(description="Roll number parser.")
    ap.add_argument("input_file")
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--mode", default="merge", choices=["merge", "replace"])
    args = ap.parse_args()

    out_name = f"rollno_{args.batch}.json"
    out_path = ROOT / out_name

    print(f"Loading {args.input_file}...")
    try:
        xl = pd.ExcelFile(args.input_file)
    except Exception:
        print("Excel read failed, trying CSV fallback...")
        # CSV fallback: treat as single-sheet core-only file.
        df = pd.read_csv(args.input_file)
        new_data = parse_sheet(df)
    else:
        new_data = build_json(xl)

    print(f"Parsed {len(new_data)} total roll entries.")

    if not new_data:
        print("VALIDATION_FAILED::No roll entries parsed — file may be empty or wrongly formatted.")
        sys.exit(2)

    if args.mode == "merge" and out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            print(f"MERGE MODE: {len(existing)} existing entries.")
            existing.update(new_data)
            final = existing
            print(f"Merged. Total: {len(final)}")
        except Exception as e:
            print(f"Error reading existing file ({e}). Writing fresh.")
            final = new_data
    else:
        print("REPLACE MODE: overwriting/creating file.")
        final = new_data

    out_path.write_text(json.dumps(final, indent=4), encoding="utf-8")
    print(f"WROTE::{out_name}::{len(final)}")


if __name__ == "__main__":
    main()
