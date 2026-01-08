import sys
import json
import re
import pandas as pd
from pathlib import Path

# --- Configuration ---
# Default output file (can be overridden by logic, but good to have)
OUT_JSON = "timetable_6th.json"
PE3_DATA = "section_pe3_data.json"  # Ensure this file exists in your repo
SRC_FILE = "timetable_input.xlsx"

# Placeholders for empty cells
BLANK = {"", "X", "---", "nan"}

# Map short days to full names
day_map = {
    'MON': 'Monday', 'TUE': 'Tuesday', 'WED': 'Wednesday',
    'THU': 'Thursday', 'FRI': 'Friday', 'SAT': 'Saturday'
}

# Mapping of time slots to room columns in the Excel/CSV
# Format: (Time Slot, Room Column Name)
time_to_room_map = [
    ('8-9',        'ROOM1'),
    ('9-10',       'ROOM2'),
    ('10-11',      'ROOM2'),  # Shares ROOM2
    ('11-12',      'ROOM3'),
    ('12-1',       'ROOM4'),
    ('1-2',        'ROOM5'),
    ('2-3',        'ROOM5'),  # Shares ROOM5
    ('3.15-4.15',  'ROOM6'),
    ('4.15-5.15',  'ROOM7'),
    ('5.15-6.15',  'ROOM7'),  # Shares ROOM7
]

# --- Helper Functions ---

def load_data(path: str) -> pd.DataFrame:
    """Loads CSV or Excel file into a Pandas DataFrame."""
    p = Path(path)
    if p.suffix in ['.xls', '.xlsx']:
        return pd.read_excel(p)
    return pd.read_csv(p)

def load_pe3_mapping(json_path: str):
    """Loads the elective mapping JSON."""
    try:
        text = Path(json_path).read_text(encoding='utf-8')
        return json.loads(text)
    except FileNotFoundError:
        print(f"Warning: {json_path} not found. Electives might not resolve correctly.")
        return {}

def resolve_elective(subject_code, section, pe3_map):
    """
    If the subject is an elective code (e.g. PE-3), 
    looks up the actual subject name using the mapping.
    """
    if subject_code == "PE-3":
        # logic to find specific elective for this section from pe3_map
        # Assuming pe3_map structure is { "SECTION": "SUBJECT_NAME" }
        return pe3_map.get(section, subject_code)
    return subject_code

def build_json(df: pd.DataFrame, pe3_map: dict) -> dict:
    """Converts the DataFrame into the target JSON structure."""
    timetable = {}

    # Iterate through each row in the dataframe
    for _, row in df.iterrows():
        # Adjust these column names if your Excel headers differ
        section  = str(row.get('SECTION', '')).strip()
        day_code = str(row.get('DAY', '')).strip().upper()

        if not section or not day_code:
            continue

        day_full = day_map.get(day_code, day_code)

        # Initialize dictionary structure
        day_dict = timetable.setdefault(section, {}).setdefault(day_full, {})

        last_room = None

        for slot, room_col in time_to_room_map:
            subject = str(row.get(slot, "")).strip()
            room    = str(row.get(room_col, "")).strip()

            # Cleanup nan values converted to string
            if subject.lower() == 'nan': subject = ""
            if room.lower() == 'nan': room = ""

            if subject in BLANK:
                continue

            # Resolve elective name
            subject = resolve_elective(subject, section, pe3_map)

            # Logic for Room Inheritance
            if room not in BLANK:
                last_room = room
            
            # Determine which room to use
            if room in BLANK:
                if subject == "HSE":
                    use_room = "TBD"
                else:
                    use_room = last_room if last_room else None
            else:
                use_room = room

            # Construct entry
            entry = {"subject": subject}
            if use_room:
                entry["room"] = use_room

            day_dict[slot] = entry

    # Clean up empty days/sections
    clean_timetable = {
        sec: {d: s for d, s in days.items() if s}
        for sec, days in timetable.items()
        if any(days.values())
    }
    return clean_timetable

# --- Main Logic ---

def main():
    # 1. Handle Input File (Passed from GitHub Action)
    if len(sys.argv) > 1:
        input_csv = sys.argv[1]
    else:
        input_csv = SRC_FILE # Fallback

    # 2. Process NEW Data
    df = load_data(input_csv) #
    pe3_map = load_pe3_mapping(PE3_DATA) #
    new_data = build_json(df, pe3_map) #

    # 3. SMART MERGE LOGIC
    output_path = Path(OUT_JSON)
    final_data = {}

    # Check if we should REPLACE or MERGE (Passed as argument)
    mode = sys.argv[2] if len(sys.argv) > 2 else "merge"

    if mode == "merge" and output_path.exists():
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            
            print(f"MERGE MODE: Found {len(existing_data)} existing sections.")
            # Update only the specific sections found in the new file
            existing_data.update(new_data)
            final_data = existing_data
            print(f"Updated. Total sections: {len(final_data)}")
        except:
            print("Error reading existing file. Overwriting.")
            final_data = new_data
    else:
        print("REPLACE MODE: Overwriting old file.")
        final_data = new_data

    # 4. Save
    output_path.write_text(json.dumps(final_data, indent=4), encoding='utf-8')

if __name__ == "__main__":
    main()