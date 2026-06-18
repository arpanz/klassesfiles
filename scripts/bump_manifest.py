"""
Bumps versions in manifest.json after a successful data write.

Increments the changed file's per-file `version` AND the top-level `manifestVersion`,
and refreshes `updatedAt`. Run by the GitHub Action right after tt_parser.py succeeds.

Usage:
    python scripts/bump_manifest.py --batch 2023 --file-type timetable
    python scripts/bump_manifest.py --batch 2024 --file-type roll
    python scripts/bump_manifest.py --batch 2024 --file-type electives
"""
import sys
import json
import argparse
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "manifest.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--file-type", required=True,
                    choices=["timetable", "electives", "roll"])
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"BUMP_FAILED::manifest.json not found at {MANIFEST}")
        sys.exit(3)

    m = json.loads(MANIFEST.read_text(encoding='utf-8'))
    cohort = next((c for c in m.get("cohorts", []) if c.get("batch") == args.batch), None)
    if cohort is None:
        print(f"BUMP_FAILED::no cohort with batch {args.batch} in manifest")
        sys.exit(3)

    node = cohort.get(args.file_type)
    if node is None:
        if args.file_type == 'electives':
            # First elective upload for this cohort — create the node and flip
            # hasElectives so the app starts fetching and merging the file.
            cohort['electives'] = {
                'name': f"electives_{args.batch}_s{cohort['semester']}.json",
                'version': 0,
            }
            cohort['hasElectives'] = True
            node = cohort['electives']
        else:
            print(f"BUMP_FAILED::cohort {args.batch} has no '{args.file_type}' file")
            sys.exit(3)

    node["version"] = int(node.get("version", 0)) + 1
    m["manifestVersion"] = int(m.get("manifestVersion", 0)) + 1
    m["updatedAt"] = datetime.datetime.utcnow().isoformat() + "Z"

    MANIFEST.write_text(json.dumps(m, indent=2) + "\n", encoding='utf-8')
    print(f"BUMPED::batch={args.batch}::{args.file_type}=v{node['version']}::"
          f"manifestVersion={m['manifestVersion']}")


if __name__ == "__main__":
    main()
