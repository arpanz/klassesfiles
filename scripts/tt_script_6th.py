import sys
import json
import pandas as pd
from pathlib import Path

# --- Configuration ---
OUT_JSON = "timetable_6th.json"
PE3_DATA = "section_pe3_data.json"
BLANK = {"", "X", "---", "nan", "NaN"}

day_map = {
    'MON': 'Monday', 'TUE': 'Tuesday', 'WED': 'Wednesday',
    'THU': 'Thursday', 'FRI': 'Friday', 'SAT': 'Saturday'
}

# 6th Sem Time Mapping
time_to_room_map = [
    ('8-9',        'ROOM1'),
    ('9-10',       'ROOM2'),
    ('10-11',      'ROOM3'),
    ('11-12',      'ROOM4'),
    ('12-1',       'ROOM5'),
    ('1-2',        'ROOM6'),
    ('2-3',        'ROOM7'),
    ('3-4',        'ROOM8'),
    ('4-5',        'ROOM9'),
    ('5-6',        'ROOM10'),
]

# --- Helper Functions ---

def load_data(path: str) -> pd.DataFrame:
    """Robust loader that tries Excel first, then CSV, regardless of extension."""
    try:
        return pd.read_excel(path)
    except Exception:
        print("Excel read failed, trying CSV...")
        return pd.read_csv(path)

def load_pe3_mapping(json_path: str):
    try:
        text = Path(json_path).read_text(encoding='utf-8')
        return json.loads(text)
    except FileNotFoundError:
        print(f"Warning: {json_path} not found.")
        return {}

def resolve_elective(subject_code, section, pe3_map):
    if subject_code == "PE-3":
        return pe3_map.get(section, subject_code)
    return subject_code

def build_json(df: pd.DataFrame, pe3_map: dict) -> dict:
    timetable = {}

    for _, row in df.iterrows():
        # FIX: Check for 'SECTION' OR 'Section'
        section = str(row.get('SECTION') or row.get('Section') or '').strip()
        
        # FIX: Check for 'DAY' OR 'Day'
        day_raw = str(row.get('DAY') or row.get('Day') or '').strip().upper()

        if not section or not day_raw:
            continue

        day_code = day_raw.split('(')[0].strip()
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

            subject = resolve_elective(subject, section, pe3_map)

            if room not in BLANK:
                last_room = room
            
            if room in BLANK:
                if subject == "HSE":
                    use_room = "TBD"
                else:
                    use_room = last_room if last_room else None
            else:
                use_room = room

            entry = {"subject": subject}
            if use_room:
                entry["room"] = use_room

            day_dict[slot] = entry

    clean_timetable = {
        sec: {d: s for d, s in days.items() if s}
        for sec, days in timetable.items()
        if any(days.values())
    }
    return clean_timetable

# --- Main Logic ---

def main():
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        print("Error: No input file provided.")
        return

    mode = sys.argv[2] if len(sys.argv) > 2 else "merge"

    print(f"Loading data from {input_file}...")
    df = load_data(input_file)
    pe3_map = load_pe3_mapping(PE3_DATA)
    new_data = build_json(df, pe3_map)
    
    print(f"Parsed {len(new_data)} sections from input file.")

    output_path = Path(OUT_JSON)
    final_data = {}

    if mode == "merge" and output_path.exists():
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            
            print(f"MERGE MODE: Found {len(existing_data)} existing sections.")
            existing_data.update(new_data)
            final_data = existing_data
            print(f"Successfully merged. Total sections: {len(final_data)}")
        except Exception as e:
            print(f"Error reading existing file ({e}). Starting fresh.")
            final_data = new_data
    else:
        print("REPLACE MODE: Overwriting/Creating new file.")
        final_data = new_data

    output_path.write_text(json.dumps(final_data, indent=4), encoding='utf-8')
    print(f"Saved to {OUT_JSON}")

if __name__ == "__main__":
    main()