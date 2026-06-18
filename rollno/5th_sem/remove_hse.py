import json
import os

INPUT_FILE = "timetable_6th.json"
OUTPUT_FILE = "timetable_6th-no_hse.json"

def remove_hse():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found.")
        return

    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        removed_count = 0
        
        # Iterate through sections
        for section, days in data.items():
            # Iterate through days
            for day, slots in days.items():
                slots_to_remove = []
                # Identify slots to remove
                for time, details in slots.items():
                    if details.get("subject") == "HSE":
                        slots_to_remove.append(time)
                
                # Remove the identified slots
                for time in slots_to_remove:
                    del slots[time]
                    removed_count += 1

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        print(f"✅ Successfully removed {removed_count} 'HSE' entries from {OUTPUT_FILE}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    remove_hse()
