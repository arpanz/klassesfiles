"""
build_electives_timetable.py
----------------------------
Read elective.csv (the file you attached) and rebuild the JSON timetable
without any “null” time-slots.  
If the room cell is blank / X / --- we inherit the room used in the
immediately preceding filled slot of the same row.

Usage
-----
$ pip install pandas
$ python build_electives_timetable.py
→ electives_timetable.json
"""
import json
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------ CONFIG ---
SRC_CSV      = "elective.csv"          # attached file[1]
OUT_JSON     = "electives_timetable.json"

BLANK        = {"", "X", "---"}
DAY_MAP      = {
    "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
    "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"
}
# keep chronological order → predecessor slot = previous tuple
TIME_TO_ROOM = [
    ("8-9",  "ROOM1"),
    ("9-10", "ROOM2"),
    ("10-11", "ROOM3"),
    ("11-12", "ROOM4"),
    ("12-1",  "ROOM5"),
    ("1-2",   "ROOM6"),
    ("3-4",   "ROOM7"),
    ("4-5",   "ROOM8"),
    ("5-6",   "ROOM9"),
]
# ---------------------------------------------------------------------------

def load_csv(path: str) -> pd.DataFrame:
    """Return cleaned DataFrame (all strings, no header repeats)."""
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    df.columns = df.columns.str.strip()
    df = df[df["DAY"].str.upper() != "DAY"]              # drop repeated headers
    df = df[df["Section(DE)"].str.strip() != ""]         # rows must have section
    return df

def build_json(df: pd.DataFrame) -> dict:
    """Convert DataFrame → nested dict without null pairs."""
    result: dict = {}

    for _, row in df.iterrows():
        section  = row["Section(DE)"].strip()
        day_full = DAY_MAP.get(row["DAY"].strip().upper())
        if not day_full:
            continue

        day_dict   = result.setdefault(section, {}).setdefault(day_full, {})
        last_room  = None

        for slot, room_col in TIME_TO_ROOM:
            subject = row.get(slot, "").strip()
            room    = row.get(room_col, "").strip()

            if subject in BLANK:                # blank class → ignore slot
                continue

            if room not in BLANK:
                last_room = room

            entry = {"subject": subject}
            if last_room:                       # inherit previous room when needed
                entry["room"] = last_room

            day_dict[slot] = entry

    # purge empty days & sections
    cleaned = {
        sec: {d: s for d, s in days.items() if s}
        for sec, days in result.items()
        if any(days.values())
    }
    return cleaned

def main():
    df   = load_csv(SRC_CSV)
    data = build_json(df)

    Path(OUT_JSON).write_text(
        json.dumps(data, indent=4, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"✅ Elective timetable written to {OUT_JSON}")

if __name__ == "__main__":
    main()
