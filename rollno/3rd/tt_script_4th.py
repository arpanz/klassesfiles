# timetable_4th_updated.py
import pandas as pd
import json
import re
from pathlib import Path

# UPDATE THIS LINE to your actual file name (can be .csv or .xlsx)
SRC_FILE = "CSE_45.xls"  
OUT_JSON = "CSE_45.json"

BLANK = {"", "X", "---"}           # placeholders that mean “no value”

day_map = {
    'MON': 'Monday', 'TUE': 'Tuesday', 'WED': 'Wednesday',
    'THU': 'Thursday', 'FRI': 'Friday', 'SAT': 'Saturday'
}

# chronological order is important → predecessor = previous item
time_to_room_map = [
    ('8-9',        'ROOM1'),
    ('9-10',       'ROOM2'),
    ('10-11',      'ROOM2'),       # shares the same room column
    ('11-12',      'ROOM3'),
    ('12-1',       'ROOM4'),
    ('1-2',        'ROOM4'),       # shares the same room column
    ('2-3',        'ROOM5'),
    ('3.00-4.00',  'ROOM6'),
    ('4.00-5.00',  'ROOM7'),
    ('5.00-6.00',  'ROOM7'),       # shares the same room column
]

# ---------------------------------------------------------------------------
def load_data(path: str) -> pd.DataFrame:
    """Loads CSV or Excel data based on file extension."""
    path_obj = Path(path)
    
    # Check extension and read accordingly
    if path_obj.suffix.lower() in ['.xls', '.xlsx']:
        df = pd.read_excel(path, dtype=str).fillna("")
    else:
        # Default to CSV behavior
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")

    # Clean columns and rows
    df.columns = df.columns.str.strip()
    if 'DAY' in df.columns:
        df['DAY'] = df['DAY'].str.replace(r'\(\d+\)', '', regex=True).str.strip()
        # Filter out header repetitions or empty rows
        df = df[(df['DAY'] != 'DAY') & df['DAY'] & df['Section']]
    
    return df

def build_json(df: pd.DataFrame) -> dict:
    timetable = {}

    for _, row in df.iterrows():
        section  = row['Section'].strip()
        # Format section numbers with leading zeros (e.g., CSE-1 -> CSE-01)
        if '-' in section:
            prefix, number = section.rsplit('-', 1)
            if number.isdigit():
                section = f"{prefix}-{int(number):02d}"
        
        day_abbr = row['DAY'].strip().upper()
        day_full = day_map.get(day_abbr)
        if not day_full:
            continue

        # ensure nested dicts exist
        day_dict = timetable\
            .setdefault(section, {})\
            .setdefault(day_full, {})

        last_room = None  # ← remembers the most recent non-blank room

        for slot, room_col in time_to_room_map:
            subject = row.get(slot, "").strip()
            room    = row.get(room_col, "").strip()

            if subject in BLANK:
                continue                      # no class → skip key entirely

            # update last_room if this room cell is *not* blank
            if room not in BLANK:
                last_room = room

            # if room is blank use the previous one (could still be None)
            use_room = last_room if last_room else None

            # write entry, *omit* room key when still unknown
            entry = {"subject": subject}
            if use_room:
                entry["room"] = use_room

            day_dict[slot] = entry

    # strip empty days / sections
    clean = {
        sec: {d: s for d, s in days.items() if s}
        for sec, days in timetable.items()
        if any(days.values())
    }
    return clean
# ---------------------------------------------------------------------------

def main():
    df   = load_data(SRC_FILE)
    data = build_json(df)

    Path(OUT_JSON).write_text(
        json.dumps(data, indent=4, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"✅ Timetable written to {OUT_JSON}")

if __name__ == "__main__":
    main()