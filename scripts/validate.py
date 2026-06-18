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

# Elective section keys have the form SUBJECT_DEPT-NN, e.g. AI_IT-01, CC_CSE-01.
# They start with a letter and may contain digits, underscores, hyphens.
ELECTIVE_SECTION_RE = re.compile(r'^[A-Z][A-Z0-9_]*-\d{2}$')

# Minimum sections expected in a real upload. A single-section revision is allowed,
# so keep this at 1; bump per-cohort if you want stricter "full file" checks.
MIN_SECTIONS = 1

# Elective placeholders that MUST have been resolved by tt_parser before writing.
# If any survive, the section was missing from section_pe3_data.json → data error.
UNRESOLVED_PLACEHOLDERS = {"PE-3", "PE-III", "PE3", "PEIII", "PE-4", "PE-IV", "PE4", "PEIV"}


def validate(data, args, elective_mode=False):
    """
    Validate parsed timetable/elective data.

    elective_mode=True uses a relaxed section-name regex (SUBJECT_DEPT-NN)
    and skips the unresolved-placeholder check (PE-3 is never in an electives
    file).
    """
    errors = []
    section_re = ELECTIVE_SECTION_RE if elective_mode else SECTION_RE

    if not data:
        errors.append("No sections parsed from the file (empty result).")
    if len(data) < MIN_SECTIONS:
        errors.append(f"Too few sections: {len(data)} (min {MIN_SECTIONS}).")

    for section, days in data.items():
        if not section_re.match(section):
            kind = "elective key (e.g. AI_IT-01)" if elective_mode else "section name (e.g. CSE-01)"
            errors.append(f"Bad {kind} '{section}'.")
        if not isinstance(days, dict) or not days:
            errors.append(f"Section '{section}' has no day data.")
            continue
        for day, slots in days.items():
            if not isinstance(slots, dict):
                errors.append(f"{section}/{day}: malformed slot data.")
                continue
            if not slots:
                errors.append(f"{section}/{day}: day has no slots.")
                continue
            for slot, info in slots.items():
                if not isinstance(info, dict) or not info.get("subject"):
                    errors.append(f"{section}/{day}/{slot}: empty/invalid subject.")
                    continue
                if not elective_mode:
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
