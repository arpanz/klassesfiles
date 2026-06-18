# timetable_6th_updated.py
import pandas as pd
import json
import re
from pathlib import Path

# UPDATE THIS LINE to your actual file name (can be .csv or .xlsx)
SRC_FILE = "your_file_here.xlsx"  
OUT_JSON = "timetable_6th.json"
PE3_DATA = "section_pe3_data.json"         # section to elective mapping

BLANK = {"", "X", "---"}           # placeholders that mean "no value"

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
    ('1-2',        'ROOM5'),
    ('2-3',        'ROOM5'),
    ('3.15-4.15',  'ROOM6'),
    ('4.15-5.15',  'ROOM7'),
    ('5.15-6.15',  'ROOM7'),
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

def load_pe3_mapping(path: str) -> dict:
    """Load the section to PE3 elective mapping"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def resolve_elective(subject: str, section: str, pe3_map: dict) -> str:
    """Replace elective codes like CC|SPM|NLP|CV with actual elective for the section"""
    # Check if subject contains pipe-separated electives
    if '|' in subject:
        # Remove dash from section name to match pe3_map keys (e.g., CSE-1 -> CSE1)
        section_key = section.replace('-', '')
        # Get the elective for this section from pe3_map
        elective = pe3_map.get(section_key)
        if elective:
            return elective
    return subject

def build_json(df: pd.DataFrame, pe3_map: dict) -> dict:
    timetable = {}

    for _, row in df.iterrows():
        section  = row['Section'].strip()

        # Format section name to ensure 2-digit number (e.g., CSE-1 -> CSE-01)
        formatted_section = re.sub(r'(\d+)$', lambda m: m.group(1).zfill(2), section)

        day_abbr = row['DAY'].strip().upper()
        day_full = day_map.get(day_abbr)
        if not day_full:
            continue

        # ensure nested dicts exist
        day_dict = timetable\
            .setdefault(formatted_section, {})\
            .setdefault(day_full, {})

        last_room = None  # ← remembers the most recent non-blank room

        for slot, room_col in time_to_room_map:
            subject = row.get(slot, "").strip()
            room    = row.get(room_col, "").strip()

            if subject in BLANK:
                continue                      # no class → skip key entirely

            # Resolve elective codes to actual elective names
            subject = resolve_elective(subject, section, pe3_map)

            # update last_room if this room cell is *not* blank
            if room not in BLANK:
                last_room = room

            # Determine room: HSE gets "TBD" if no room, others use previous room
            if room in BLANK:
                if subject == "HSE":
                    use_room = "TBD"
                else:
                    use_room = last_room if last_room else None
            else:
                use_room = room

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
    pe3_map = load_pe3_mapping(PE3_DATA)
    data = build_json(df, pe3_map)

    Path(OUT_JSON).write_text(
        json.dumps(data, indent=4, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"✅ Timetable written to {OUT_JSON}")

if __name__ == "__main__":
    main()