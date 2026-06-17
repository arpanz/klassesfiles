"""
Validation gate for timetable uploads.

`validate(data, args)` is called by tt_parser.py BEFORE anything is written.
On failure it prints a machine-readable `VALIDATION_FAILED::<reasons>` line (so the
GitHub Action can forward it to Telegram) and exits non-zero, aborting the commit.

The checks here are intentionally structural + format-based so that garbage / empty /
wrong-shape files never reach the live JSON. Extend `KNOWN_SUBJECTS` per cohort later
(sourced from subjects_by_semester.json) for stronger cohort-mismatch detection.
"""
import sys
import re

# Sections look like CSE-01, CSCE-01, IT-01, CSSE-01 (letters, hyphen, two digits).
SECTION_RE = re.compile(r'^[A-Z]+-\d{2}$')

# Minimum sections expected in a real upload. A single-section revision is allowed,
# so keep this at 1; bump per-cohort if you want stricter "full file" checks.
MIN_SECTIONS = 1

# Elective placeholders that MUST have been resolved by tt_parser before writing.
# If any survive, the section was missing from section_pe3_data.json → data error.
UNRESOLVED_PLACEHOLDERS = {"PE-3", "PE-III", "PE3", "PEIII", "PE-4", "PE-IV", "PE4", "PEIV"}


def validate(data, args):
    errors = []

    if not data:
        errors.append("No sections parsed from the file (empty result).")
    if len(data) < MIN_SECTIONS:
        errors.append(f"Too few sections: {len(data)} (min {MIN_SECTIONS}).")

    for section, days in data.items():
        if not SECTION_RE.match(section):
            errors.append(f"Bad section name '{section}' (expected like CSE-01).")
        if not isinstance(days, dict) or not days:
            errors.append(f"Section '{section}' has no day data.")
            continue
        for day, slots in days.items():
            if not isinstance(slots, dict):
                errors.append(f"{section}/{day}: malformed slot data.")
                continue
            for slot, info in slots.items():
                if not isinstance(info, dict) or not info.get("subject"):
                    errors.append(f"{section}/{day}/{slot}: empty/invalid subject.")
                    continue
                subj = info["subject"]
                norm = subj.upper().replace(" ", "")
                # Unresolved elective: leftover PE-3 placeholder or pipe-options.
                if norm in UNRESOLVED_PLACEHOLDERS or "|" in subj:
                    errors.append(
                        f"{section}/{day}/{slot}: unresolved elective '{subj}' "
                        f"— section likely missing from section_pe3_data.json."
                    )

    if errors:
        # First 10 reasons keep the Telegram message readable.
        print("VALIDATION_FAILED::" + " | ".join(errors[:10]))
        sys.exit(2)

    print(f"VALIDATION_OK::{len(data)} sections")
