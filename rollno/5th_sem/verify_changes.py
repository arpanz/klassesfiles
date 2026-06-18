import json

def check_changes():
    try:
        with open("timetable_6th_old.json", 'r', encoding='utf-8') as f:
            old = json.load(f)
        with open("timetable_6th.json", 'r', encoding='utf-8') as f:
            new = json.load(f)

        changes = []
        
        # Check for modified values in existing keys
        for sec in new:
            if sec not in old:
                continue
            for day in new[sec]:
                if day not in old[sec]:
                    continue
                for time in new[sec][day]:
                    if time not in old[sec][day]:
                        continue
                    
                    val_old = old[sec][day][time]
                    val_new = new[sec][day][time]
                    
                    if val_old != val_new:
                        changes.append({
                            "path": f"{sec}.{day}.{time}",
                            "old": val_old,
                            "new": val_new
                        })

        print(f"Found {len(changes)} modified entries (excluding removals/additions).")
        for c in changes:
            print(f"[CHANGED] {c['path']}")
            print(f"  OLD: {c['old']}")
            print(f"  NEW: {c['new']}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_changes()
