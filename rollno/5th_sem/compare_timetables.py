import json
import os

FILE_OLD = "timetable_6th_old.json"
FILE_NEW = "timetable_6th.json"

def load_json(filepath):
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found.")
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def compare_dicts(d1, d2, path=""):
    """
    Recursively compare two dictionaries.
    d1: Old dictionary
    d2: New dictionary
    path: Current path in the JSON structure
    """
    all_keys = set(d1.keys()) | set(d2.keys())
    
    for key in sorted(all_keys):
        new_path = f"{path}.{key}" if path else key
        
        if key not in d1:
            print(f"[ADDED] {new_path}: {d2[key]}")
        elif key not in d2:
            print(f"[REMOVED] {new_path}: {d1[key]}")
        else:
            val1 = d1[key]
            val2 = d2[key]
            
            if isinstance(val1, dict) and isinstance(val2, dict):
                compare_dicts(val1, val2, new_path)
            elif val1 != val2:
                print(f"[CHANGED] {new_path}:")
                print(f"  OLD: {val1}")
                print(f"  NEW: {val2}")

def main():
    print(f"Comparing {FILE_OLD} vs {FILE_NEW}...\n")
    
    data_old = load_json(FILE_OLD)
    data_new = load_json(FILE_NEW)
    
    if data_old is None or data_new is None:
        return

    compare_dicts(data_old, data_new)
    print("\nComparison complete.")

if __name__ == "__main__":
    main()
