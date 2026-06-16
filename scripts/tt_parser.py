"""
Generalized timetable parser (replaces tt_script_4th.py + tt_script_6th.py).

Parses an Excel/CSV timetable sheet and writes a batch-named JSON file:
    timetable_{batch}_s{semester}.json   e.g. timetable_2023_s6.json

It is parameterized by --batch / --semester and an optional --pe3 flag:
  * --pe3  : run section-assigned elective resolution (the old "6th sem" behavior),
             baking PE-3 / pipe-separated electives into the main timetable using
             section_pe3_data.json. Omit it for sems with no section-assigned elective
             (the old "4th sem" behavior).

All original parsing logic is preserved: dynamic ROOM-column mapping, room
carry-forward, case-insensitive SECTION/DAY, section normalization (cse-1 -> cse-01),
and merge/replace modes.

Usage:
    python scripts/tt_parser.py input.xlsx --batch 2023 --semester 6 --mode merge --pe3
"""
import sys
import json
import re
import argparse
import pandas as pd
from pathlib import Path

# validate.py lives in the same dir; sys.path[0] is that dir when run as a script.
from validate import validate

ROOT = Path(__file__).resolve().parent.parent          # repo root
PE3_DATA = Path(__file__).parent / "section_pe3_data.json"
BLANK = {"", "X", "---", "nan", "NaN", "HSE"}

day_map = {
    'MON': 'Monday', 'TUE': 'Tuesday', 'WED': 'Wednesday',
    'THU': 'Thursday', 'FRI': 'Friday', 'SAT': 'Saturday',
}

# Superset of all time-slot header variants seen across sems (4th used 3-4/4-5/5-6,
# 6th used 3.00-4.00 style). Harmless to include all; only matching columns are used.
TIME_SLOTS = [
    '8-9', '9-10', '10-11', '11-12', '12-1', '1-2', '2-3',
    '3.00-4.00', '4.00-5.00', '5.00-6.00', '3-4', '4-5', '5-6',
]


# ----------------------------- helpers -----------------------------
def load_data(path: str) -> pd.DataFrame:
    """Try Excel first, fall back to CSV regardless of extension."""
    try:
        return pd.read_excel(path)
    except Exception:
        print("Excel read failed, trying CSV...")
        return pd.read_csv(path)


def normalize_section(section: str) -> str:
    """Pad single-digit section numbers: 'cse-1' -> 'cse-01'."""
    if not section:
        return section
    return re.sub(r'(?<!\d)(\d)(?!\d)', r'0\1', section)


def load_pe3_mapping():
    try:
        data = json.loads(PE3_DATA.read_text(encoding='utf-8'))
        return {normalize_section(k): v for k, v in data.items()}
    except FileNotFoundError:
        print(f"Warning: {PE3_DATA} not found; PE-3 resolution disabled.")
        return {}


def resolve_elective(subject_code, section, pe3_map):
    subj_norm = subject_code.upper().replace(" ", "")
    elective = None
    for key in [section, section.replace(" ", ""), section.replace("-", ""),
                section.replace(" ", "").replace("-", "")]:
        if key in pe3_map:
            elective = pe3_map[key]
            break
    # Explicit PE-3 placeholder
    if subj_norm in ["PE-3", "PE-III", "PE3", "PEIII"]:
        return elective if elective else subject_code
    # Merged pipe-separated options, e.g. "CC|SPM|NLP|CV"
    if "|" in subject_code:
        options = [s.strip().upper() for s in subject_code.split("|")]
        if elective and elective.upper() in options:
            return elective
    return subject_code


def build_json(df: pd.DataFrame, pe3_map: dict, pe3: bool) -> dict:
    timetable = {}

    # Dynamically pair each time-slot column with the most recent ROOM* column.
    time_to_room_map = []
    current_room_col = None
    for col in df.columns:
        col_str = str(col).strip()
        if "ROOM" in col_str.upper():
            current_room_col = col_str
        elif col_str in TIME_SLOTS and current_room_col:
            time_to_room_map.append((col_str, current_room_col))

    for _, row in df.iterrows():
        section_raw = str(row.get('SECTION') or row.get('Section') or '').strip()
        section = normalize_section(section_raw)
        day_raw = str(row.get('DAY') or row.get('Day') or '').strip().upper()

        if not section or not day_raw:
            continue

        day_code = day_raw.split('(')[0].strip()
        day_full = day_map.get(day_code, day_code)

        day_dict = timetable.setdefault(section, {}).setdefault(day_full, {})
        last_room = None

        for slot, room_col in time_to_room_map:
            subject = str(row.get(slot, "")).strip()
            room = str(row.get(room_col, "")).strip()

            if subject.lower() == 'nan':
                subject = ""
            if room.lower() == 'nan':
                room = ""

            if subject in BLANK:
                continue

            if pe3:
                subject = resolve_elective(subject, section, pe3_map)

            if room not in BLANK:
                last_room = room
            use_room = last_room if room in BLANK else room

            entry = {"subject": subject}
            if use_room:
                entry["room"] = use_room
            day_dict[slot] = entry

    return {
        sec: {d: s for d, s in days.items() if s}
        for sec, days in timetable.items()
        if any(days.values())
    }


# ------------------------------ main ------------------------------
def main():
    ap = argparse.ArgumentParser(description="Generalized timetable parser.")
    ap.add_argument("input_file")
    ap.add_argument("--batch", type=int, required=True, help="Admission year, e.g. 2023")
    ap.add_argument("--semester", type=int, required=True, help="Semester number, e.g. 6")
    ap.add_argument("--mode", default="merge", choices=["merge", "replace"])
    ap.add_argument("--pe3", action="store_true",
                    help="Run section-assigned (PE-3) elective resolution.")
    args = ap.parse_args()

    out_name = f"timetable_{args.batch}_s{args.semester}.json"
    out_path = ROOT / out_name

    print(f"Loading data from {args.input_file}...")
    df = load_data(args.input_file)
    pe3_map = load_pe3_mapping() if args.pe3 else {}
    new_data = build_json(df, pe3_map, args.pe3)
    print(f"Parsed {len(new_data)} sections from input file.")

    # ---- validation gate (aborts on failure) ----
    validate(new_data, args)

    if args.mode == "merge" and out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding='utf-8'))
            print(f"MERGE MODE: found {len(existing)} existing sections.")
            existing.update(new_data)
            final = existing
            print(f"Merged. Total sections: {len(final)}")
        except Exception as e:
            print(f"Error reading existing file ({e}). Writing fresh.")
            final = new_data
    else:
        print("REPLACE MODE: overwriting/creating file.")
        final = new_data

    out_path.write_text(json.dumps(final, indent=4), encoding='utf-8')
    # stdout contract parsed by the GitHub Action for the Telegram summary:
    print(f"WROTE::{out_name}::{len(final)}")


if __name__ == "__main__":
    main()
