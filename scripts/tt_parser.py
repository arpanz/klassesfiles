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
import copy
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
    'MONDAY': 'Monday', 'TUESDAY': 'Tuesday', 'WEDNESDAY': 'Wednesday',
    'THURSDAY': 'Thursday', 'FRIDAY': 'Friday', 'SATURDAY': 'Saturday',
}

# Mapping for newer period formats (e.g. P1\n08:00 -> 8-9)
PERIOD_MAP = {
    'P1': '8-9',
    'P2': '9-10',
    'P3': '10-11',
    'P4': '11-12',
    'P5': '12-1',
    'P6': '1-2',
    'P7': '2-3',
    'P8': '3-4',
    'P9': '4-5',
    'P10': '5-6',
}

# Superset of all time-slot header variants seen across sems. Harmless to include all;
# only columns whose header exactly matches an entry here are parsed.
#   4th sem used:  3-4 / 4-5 / 5-6
#   6th sem used:  3.00-4.00 / 4.00-5.00 / 5.00-6.00
#   3rd sem used:  3.15-4.15 / 4.15-5.15 / 5.15-6.15
# Add new variants here whenever a new semester sheet uses a different time format.
TIME_SLOTS = [
    '8-9', '9-10', '10-11', '11-12', '12-1', '1-2', '2-3',
    '3.00-4.00', '4.00-5.00', '5.00-6.00',
    '3-4',       '4-5',       '5-6',
    '3.15-4.15', '4.15-5.15', '5.15-6.15',
]


# ----------------------------- helpers -----------------------------
def clean_header_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Automatically promotes the first row containing 'day' and 'section' keywords to columns if needed."""
    has_day = any('day' in str(c).lower() for c in df.columns)
    has_section = any('section' in str(c).lower() for c in df.columns)
    
    if not (has_day and has_section):
        for idx, row in df.head(10).iterrows():
            row_vals = [str(val).strip().lower() for val in row.values]
            found_day = any('day' in val for val in row_vals)
            found_section = any('section' in val for val in row_vals)
            if found_day and found_section:
                df.columns = [str(val).strip() for val in row.values]
                df = df.iloc[idx + 1:].reset_index(drop=True)
                break
    return df


def load_data(path: str) -> pd.DataFrame:
    """Try Excel first (picking the correct sheet if multiple exist), fall back to CSV."""
    try:
        xl = pd.ExcelFile(path)
        sheet_name = xl.sheet_names[0]
        # Search for a sheet that looks like it has the grid / timetable data
        for name in xl.sheet_names:
            name_low = name.lower()
            if "grid" in name_low or "timetable" in name_low or "schedule" in name_low or "section" in name_low or "class" in name_low:
                if "summary" not in name_low:
                    sheet_name = name
                    break
        print(f"Reading sheet: '{sheet_name}'")
        df = xl.parse(sheet_name)
    except Exception:
        print("Excel read failed, trying CSV...")
        df = pd.read_csv(path)
    return clean_header_rows(df)


SECTION_REGEX = re.compile(r"^([A-Z]+)(?:-?)(\d+)$", re.I)


def normalize_section(section: str, is_elective: bool = False) -> str:
    """Normalize and pad section numbers: 'cse-1' -> 'CSE-01', 'IT02' -> 'IT-02', 'AI_IT-1' -> 'AI_IT-01'."""
    if not section:
        return section
    section = section.strip()
    if "|" in section:
        section = section.split("|")[-1].strip()
    if "_" in section:
        parts = section.split("_", 1)
        return f"{parts[0].upper()}_{normalize_section(parts[1], is_elective=True)}"
    m = SECTION_REGEX.match(section.replace(" ", ""))
    if not m:
        return section.upper()
    prefix, num = m.groups()
    prefix_upper = prefix.upper()
    if prefix_upper == "CS" and not is_elective:
        prefix_upper = "CSE"
    return f"{prefix_upper}-{int(num):02d}"


def normalize_room(room: str) -> str:
    """Normalize room names: C25-A308 -> C25-A-308, C25-B110 -> C25-B-110."""
    if not room:
        return room
    room = room.strip()
    m = re.match(r'^C25-([A-Z])(\d+)(.*)$', room, re.I)
    if m:
        block, num, suffix = m.groups()
        return f"C25-{block.upper()}-{num}{suffix}"
    return room


def parse_combined_cell(cell_value: str):
    """
    Parses a cell containing subject, faculty, and room separated by newlines.
    Returns (subject, room).
    """
    if not cell_value or str(cell_value).lower() == 'nan':
        return "", ""
    lines = [line.strip() for line in str(cell_value).split('\n') if line.strip()]
    if not lines:
        return "", ""
    
    subject = lines[0]
    room = ""
    
    if len(lines) >= 3:
        # Format: Subject \n Faculty \n Room
        room = lines[2]
    elif len(lines) == 2:
        # Format: Subject \n Room (or Subject \n Faculty)
        second = lines[1]
        if any(p in second.upper() for p in ["C25", "ROOM", "LAB", "HALL", "C-"]) or re.search(r'\d', second):
            room = second
            
    return subject, room


def build_json(df: pd.DataFrame) -> dict:
    timetable = {}

    # Rename columns like P1\n08:00 -> 8-9 based on PERIOD_MAP
    renamed_cols = {}
    for col in df.columns:
        col_str = str(col).strip()
        parts = col_str.split('\n')
        p_part = parts[0].upper().strip()
        if p_part in PERIOD_MAP:
            renamed_cols[col] = PERIOD_MAP[p_part]
    if renamed_cols:
        df = df.rename(columns=renamed_cols)

    # Check if there is any ROOM column
    has_room_cols = any("ROOM" in str(col).upper() for col in df.columns)

    # Dynamically pair each time-slot column with the most recent ROOM* column.
    time_to_room_map = []
    if has_room_cols:
        current_room_col = None
        for col in df.columns:
            col_str = str(col).strip()
            if "ROOM" in col_str.upper():
                current_room_col = col_str
            elif col_str in TIME_SLOTS and current_room_col:
                time_to_room_map.append((col_str, current_room_col))
    else:
        # No separate ROOM columns - slot columns themselves contain room info
        for col in df.columns:
            col_str = str(col).strip()
            if col_str in TIME_SLOTS:
                time_to_room_map.append((col_str, None))

    # Find the section and day columns case-insensitively with fallback
    section_col = None
    day_col = None
    for col in df.columns:
        c_low = str(col).strip().lower()
        if c_low == 'section' or c_low == 'branch' or 'section(' in c_low:
            section_col = col
            break
    if not section_col:
        for col in df.columns:
            if 'section' in str(col).lower():
                section_col = col
                break

    for col in df.columns:
        c_low = str(col).strip().lower()
        if c_low == 'day':
            day_col = col
            break
    if not day_col:
        for col in df.columns:
            if 'day' in str(col).lower():
                day_col = col
                break

    for _, row in df.iterrows():
        section_raw = str(row[section_col]).strip() if section_col else str(row.get('SECTION') or row.get('Section') or '').strip()
        section = normalize_section(section_raw)
        day_raw = str(row[day_col]).strip().upper() if day_col else str(row.get('DAY') or row.get('Day') or '').strip().upper()

        if not section or not day_raw:
            continue

        # Skip repeated header rows that some Excel exports embed in the data
        # (e.g. a row where the section cell literally says "Section").
        if section_raw.lower() in ('section', 'day', 'nan'):
            continue

        day_code = day_raw.split('(')[0].strip()
        day_full = day_map.get(day_code, day_code)

        day_dict = timetable.setdefault(section, {}).setdefault(day_full, {})
        last_room = None

        for slot, room_col in time_to_room_map:
            if room_col:
                subject = str(row.get(slot, "")).strip()
                room = str(row.get(room_col, "")).strip()

                if subject.lower() == 'nan':
                    subject = ""
                if room.lower() == 'nan':
                    room = ""

                if subject in BLANK:
                    continue

                if room not in BLANK:
                    last_room = room
                use_room = last_room if room in BLANK else room
            else:
                # Combined cell
                cell_val = str(row.get(slot, "")).strip()
                if not cell_val or cell_val.lower() == 'nan' or cell_val in BLANK:
                    continue
                subject, room = parse_combined_cell(cell_val)
                if not subject or subject in BLANK:
                    continue
                use_room = room

            use_room = normalize_room(use_room)
            entry = {"subject": subject}
            if use_room:
                entry["room"] = use_room
            day_dict[slot] = entry

    return {
        sec: {d: s for d, s in days.items() if s}
        for sec, days in timetable.items()
        if any(days.values())
    }


# ------------------------------ merge ------------------------------
def deep_merge(old: dict, new: dict) -> dict:
    """
    Merge `new` into `old` at section -> day -> slot granularity.

    A top-level ``dict.update`` would replace a whole section, so a partial
    upload (e.g. a sheet containing only Monday for CSE-01) would WIPE that
    section's other days. This merges down to the individual slot, so only the
    slots actually present in `new` are overwritten; every existing day/slot the
    upload doesn't mention is preserved.
    """
    final = copy.deepcopy(old)
    for sec, days in new.items():
        sec_dict = final.setdefault(sec, {})
        for day, slots in days.items():
            day_dict = sec_dict.setdefault(day, {})
            for slot, entry in slots.items():
                day_dict[slot] = entry
    return final


# ------------------------------ diff ------------------------------
# Thresholds for flagging a "BIG" (held-for-approval) change. Tune freely.
MAX_NEW_SECTIONS = 2       # more than this many brand-new sections → BIG
MAX_TOUCHED_SECTIONS = 5   # more than this many added+modified sections → BIG
MAX_OVERWRITTEN_SLOTS = 8  # more than this many EXISTING slots rewritten → BIG


def _slot_diff_stats(old: dict, new: dict):
    """
    Count slot-level changes between two timetables, looking only at sections
    that exist in BOTH (so whole-section adds/removes are handled separately).

    Returns (new_slots, overwritten_slots, removed_slots):
      new_slots         - slot present in `new` but not `old`   (filling a gap)
      overwritten_slots - slot present in both, different value (existing data changed)
      removed_slots     - slot present in `old` but not `new`   (data deleted)
    """
    new_slots = overwritten = removed = 0
    for sec in set(old) & set(new):
        o_sec, n_sec = old.get(sec, {}), new.get(sec, {})
        for day in set(o_sec) | set(n_sec):
            o_day, n_day = o_sec.get(day, {}), n_sec.get(day, {})
            for slot in set(o_day) | set(n_day):
                o, n = o_day.get(slot), n_day.get(slot)
                if o == n:
                    continue
                if o is None:
                    new_slots += 1
                elif n is None:
                    removed += 1
                else:
                    overwritten += 1
    return new_slots, overwritten, removed


def classify_change(old: dict, new: dict):
    """
    Decide whether a change is SMALL (auto-publish) or BIG (hold for approval).
    Returns (level, reasons) where level is 'SMALL' or 'BIG'.

    Section-level rules catch structural changes (sections added/removed). The
    slot-level rules catch the merge-mode blind spot: a wrong-but-valid file can
    rewrite or delete the *contents* of a few existing sections without removing
    any section, so it would never trip the section-count rules. Counting the
    actual overwritten/removed slots holds those for approval too.
    """
    old_secs, new_secs = set(old), set(new)
    added = new_secs - old_secs
    removed = old_secs - new_secs
    modified = {s for s in (old_secs & new_secs) if old.get(s) != new.get(s)}
    touched = len(added) + len(modified)
    new_slots, overwritten_slots, removed_slots = _slot_diff_stats(old, new)

    reasons = []
    if removed:
        reasons.append(f"{len(removed)} section(s) removed")
    if len(added) > MAX_NEW_SECTIONS:
        reasons.append(f"{len(added)} new sections")
    if touched > MAX_TOUCHED_SECTIONS:
        reasons.append(f"{touched} sections changed")
    if overwritten_slots > MAX_OVERWRITTEN_SLOTS:
        reasons.append(f"{overwritten_slots} existing slots overwritten")
    if removed_slots:
        reasons.append(f"{removed_slots} existing slot(s) deleted")

    return ("BIG" if reasons else "SMALL"), reasons


def _fmt_entry(e):
    """Render a slot entry like 'AI(L) @ C25-A-102' for the diff."""
    if not e:
        return "(none)"
    subj = e.get("subject", "?")
    room = e.get("room")
    return f"{subj} @ {room}" if room else subj


def compute_changes(old: dict, new: dict, max_detail: int = 20) -> list:
    """Human-readable, capped list of what changed between old and new."""
    old_secs, new_secs = set(old), set(new)
    added = sorted(new_secs - old_secs)
    removed = sorted(old_secs - new_secs)

    detail = []
    total_slot_changes = 0
    modified_sections = set()

    for sec in sorted(old_secs & new_secs):
        o_sec, n_sec = old.get(sec, {}), new.get(sec, {})
        for day in sorted(set(o_sec) | set(n_sec)):
            o_day, n_day = o_sec.get(day, {}), n_sec.get(day, {})
            for slot in sorted(set(o_day) | set(n_day)):
                o, n = o_day.get(slot), n_day.get(slot)
                if o == n:
                    continue
                modified_sections.add(sec)
                total_slot_changes += 1
                if len(detail) < max_detail:
                    if o is None:
                        detail.append(f"+ {sec} {day} {slot}: {_fmt_entry(n)}")
                    elif n is None:
                        detail.append(f"- {sec} {day} {slot}: removed")
                    else:
                        detail.append(
                            f"~ {sec} {day} {slot}: {_fmt_entry(o)} -> {_fmt_entry(n)}"
                        )

    summary = []
    if added:
        summary.append(f"Sections added ({len(added)}): {', '.join(added)}")
    if removed:
        summary.append(f"Sections removed ({len(removed)}): {', '.join(removed)}")
    if modified_sections:
        summary.append(
            f"Sections modified ({len(modified_sections)}): "
            f"{', '.join(sorted(modified_sections))}"
        )
    if not summary:
        summary.append("No content changes (data identical).")

    out = summary + detail
    if total_slot_changes > max_detail:
        out.append(f"...and {total_slot_changes - max_detail} more slot changes")
    return out


# ------------------------------ main ------------------------------
def main():
    ap = argparse.ArgumentParser(description="Generalized timetable parser.")
    ap.add_argument("input_file")
    ap.add_argument("--batch", type=int, required=True, help="Admission year, e.g. 2023")
    ap.add_argument("--semester", type=int, required=True, help="Semester number, e.g. 6")
    ap.add_argument("--mode", default="merge", choices=["merge", "replace"])
    ap.add_argument("--pe3", action="store_true",
                    help="Deprecated (ignored). Previously ran section-assigned (PE-3) elective resolution.")
    ap.add_argument("--file-type", default="timetable", choices=["timetable", "electives"],
                    help="Type of timetable file (timetable or electives).")
    args = ap.parse_args()

    prefix = "timetable" if args.file_type == "timetable" else "electives"
    out_name = f"{prefix}_{args.batch}_s{args.semester}.json"
    out_path = ROOT / out_name

    print(f"Loading data from {args.input_file}...")
    df = load_data(args.input_file)
    new_data = build_json(df)
    print(f"Parsed {len(new_data)} sections from input file.")

    # ---- validation gate (aborts on failure) ----
    validate(new_data, args)

    # Load the current on-disk version (for both merge and the diff report).
    old_disk = {}
    if out_path.exists():
        try:
            old_disk = json.loads(out_path.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"Warning: could not read existing file for diff ({e}).")
            old_disk = {}

    if args.mode == "merge" and old_disk:
        print(f"MERGE MODE: found {len(old_disk)} existing sections.")
        final = deep_merge(old_disk, new_data)
        print(f"Merged. Total sections: {len(final)}")
    else:
        print("REPLACE MODE: overwriting/creating file.")
        final = new_data

    # Compute the human-readable diff and classify it (SMALL vs BIG).
    changes = compute_changes(old_disk, final)
    level, reasons = classify_change(old_disk, final)
    (ROOT / "change_level.txt").write_text(level, encoding='utf-8')

    header = []
    if level == "BIG":
        header = ["FLAGGED AS BIG CHANGE: " + "; ".join(reasons), ""]
    (ROOT / "changes.txt").write_text(
        "\n".join(header + changes), encoding='utf-8'
    )
    print("CHANGE_LEVEL::" + level)
    print("CHANGES_BEGIN")
    for line in (header + changes):
        print(line)
    print("CHANGES_END")

    out_path.write_text(json.dumps(final, indent=4), encoding='utf-8')
    # stdout contract parsed by the GitHub Action for the Telegram summary:
    print(f"WROTE::{out_name}::{len(final)}")


if __name__ == "__main__":
    main()
