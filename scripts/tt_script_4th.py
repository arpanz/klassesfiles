import sys
import json
import re
import pandas as pd
from pathlib import Path

# --- Configuration ---
OUT_JSON = "timetable_4th.json"
SRC_FILE = "timetable_input.xlsx"

BLANK = {"", "X", "---", "nan"}

day_map = {
    'MON': 'Monday', 'TUE': 'Tuesday', 'WED': 'Wednesday',
    'THU': 'Thursday', 'FRI': 'Friday', 'SAT': 'Saturday'
}

# 4th Sem Time Mapping
# Format: (Time Slot, Room Column Name)
time_to_room_map = [
    ('8-9',        'ROOM1'),
    ('9-10',       'ROOM2'),
    ('10-11',      'ROOM2'),
    ('11-12',      'ROOM3'),
    ('12-1',       'ROOM4'),
    ('1-2',        'ROOM4'),
    ('2-3',        'ROOM5'),
    ('3.00-4.00',  'ROOM6'),
    ('4.00-5.00',  'ROOM7'),
    ('5.00-6.00',  'ROOM7'),
]

# --- Helper Functions ---

def load_data(path: str) -> pd.DataFrame:
    """Loads CSV or Excel file into a Pandas DataFrame."""
    p = Path(path)
    if p.suffix in ['.xls', '.xlsx']:
        return pd.read_excel(p)
    return pd.read_csv(p)

def build_json(df: pd.DataFrame) -> dict:
    """Converts the DataFrame into the target JSON structure."""
    timetable = {}

    for _, row in df.iterrows():
        section  = str(row.get('SECTION', '')).strip()
        day_code = str(row.get('DAY', '')).strip().upper()

        if not section or not day_code:
            continue

        day_full = day_map.get(day_code, day_code)
        
        day_dict = timetable.setdefault(section, {}).setdefault(day_full, {})

        last_room = None

        for slot, room_col in time_to_room_map:
            subject = str(row.get(slot, "")).strip()
            room    = str(row.get(room_col, "")).strip()

            if subject.lower() == 'nan': subject = ""
            if room.lower() == 'nan': room = ""

            if subject in BLANK:
                continue

            if room not in BLANK:
                last_room = room

            use_room = last_room if last_room else None

            entry = {"subject": subject}
            if use_room:
                entry["room"] = use_room

            day_dict[slot] = entry

    # Strip empty entries
    clean_timetable = {
        sec: {d: s for d, s in days.items() if s}
        for sec, days in timetable.items()
        if any(days.values())
    }
    return clean_timetable

# --- Main Logic ---

def main():
    # 1. Handle Input File
    if len(sys.argv) > 1:
        input_csv = sys.argv[1]
    else:
        input_csv = SRC_FILE

    # 2. Process NEW Data (No PE3 map for 4th sem)
    df = load_data(input_csv) #
    new_data = build_json(df) #

    # 3. SMART MERGE LOGIC
    output_path = Path(OUT_JSON)
    final_data = {}

    mode = sys.argv[2] if len(sys.argv) > 2 else "merge"

    if mode == "merge" and output_path.exists():
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            existing_data.update(new_data)
            final_data = existing_data
            print(f"Merged. Total sections: {len(final_data)}")
        except:
            final_data = new_data
    else:
        final_data = new_data

    # 4. Save
    output_path.write_text(json.dumps(final_data, indent=4), encoding='utf-8')

if __name__ == "__main__":
    main()