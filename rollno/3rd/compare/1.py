from __future__ import annotations
import json
import re
import sys
from pathlib import Path

# A set of valid day names used for validation.
DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}

# Pre-compiled regex for efficiently parsing section names.
SECTION_REGEX = re.compile(r"^([A-Z]+)(?:-?)(\d+)$", re.I)

def norm_section(raw: str) -> str:
    """
    Normalizes different formats of section names into a single, consistent format.
    For example: 'CSE-01' -> 'CSE-1', 'IT01' -> 'IT-1', 'csce-3' -> 'CSCE-3'.
    
    This is the key function that allows comparison between your two files.
    """
    # Clean up whitespace and attempt to match the standard pattern.
    m = SECTION_REGEX.match(raw.replace(" ", ""))
    if not m:
        return raw.strip()  # If the pattern is unknown, return it as is.
    
    prefix, num = m.groups()
    # Reconstruct the name in 'DEPT-NUM' format. Using int() removes leading zeros.
    return f"{prefix.upper()}-{int(num)}"

def flatten(data: dict) -> dict[tuple[str, str, str], dict]:
    """
    Converts the nested timetable structure into a flat dictionary.
    The new key is a tuple of (section, day, slot) for easy lookup.
    Example: {('CSE-1', 'Monday', '11-12'): {'subject': 'DS', 'room': 'C25-B-107'}}
    """
    flat = {}
    for sec_raw, day_map in data.items():
        sec = norm_section(sec_raw)  # Normalize the section name first.
        for day, slots in day_map.items():
            for slot, entry in slots.items():
                flat[(sec, day, slot)] = entry
    return flat

def compare(a: dict, b: dict, file_a_name: str, file_b_name: str) -> None:
    """
    Compares two flattened timetable dictionaries and reports the differences.
    """
    only_a, only_b, sub_diff, room_diff = [], [], [], []

    # Combine all unique keys from both dictionaries to ensure nothing is missed.
    all_keys = set(a) | set(b)

    for key in sorted(list(all_keys)):  # Sorting provides an orderly report.
        # Check for entries that are exclusive to one file.
        if key not in b:
            only_a.append(key)
            continue
        if key not in a:
            only_b.append(key)
            continue

        # Retrieve subject and room details for comparison.
        sa, sb = a[key].get("subject"), b[key].get("subject")
        ra, rb = a[key].get("room"), b[key].get("room")

        # Check for mismatches in subject or room.
        if sa != sb:
            sub_diff.append((key, f"'{sa}' vs '{sb}'"))
        # Only check for room differences if the subjects are the same.
        elif ra != rb:
            room_diff.append((key, f"'{ra}' vs '{rb}'"))

    def show(title: str, seq: list):
        print(f"\n─── {title}: {len(seq)} ───")
        if not seq:
            print("None found.")
        for item in seq:
            print(item)

    # Display the final report.
    show(f"Entries present in '{file_a_name}' but MISSING in '{file_b_name}'", only_a)
    show(f"Entries MISSING in '{file_a_name}' but present in '{file_b_name}'", only_b)
    show("SUBJECT mismatches", sub_diff)
    show("ROOM mismatches (where subjects match)", room_diff)

def main():
    """
    Main function to execute the script.
    """
    if len(sys.argv) != 3:
        sys.exit(f"Usage: python {sys.argv[0]} <fileA.json> <fileB.json>")
    
    file_a_path = Path(sys.argv[1])
    file_b_path = Path(sys.argv[2])

    print(f"Comparing File A: {file_a_path.name}")
    print(f"With      File B: {file_b_path.name}\n")

    a = json.loads(file_a_path.read_text(encoding="utf-8"))
    b = json.loads(file_b_path.read_text(encoding="utf-8"))

    # Flatten both data structures for comparison.
    flat_a, flat_b = flatten(a), flatten(b)
    print(f"Total normalized entries in A: {len(flat_a)}")
    print(f"Total normalized entries in B: {len(flat_b)}")

    # Run the comparison and print the report.
    compare(flat_a, flat_b, file_a_path.name, file_b_path.name)

if __name__ == "__main__":
    main()