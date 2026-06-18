import pandas as pd
import json

def create_timetable_from_csv(core_df):
    """
    Reads the core timetable DataFrame and converts it into a structured
    dictionary that mimics the JSON format.
    """
    timetable = {}

    # Drop the '2.15-3.15' column if it exists, as it's often a break time
    if '2.15-3.15' in core_df.columns:
        core_df = core_df.drop(columns=['2.15-3.15'])

    time_slots = core_df.columns[2:]  # Get all time slot column names

    current_branch = None
    for index, row in core_df.iterrows():
        # Handle potentially merged 'Branch' cells in the original Excel
        if pd.notna(row['Branch']):
            current_branch = row['Branch'].strip()
        
        if not current_branch:
            continue

        if current_branch not in timetable:
            timetable[current_branch] = {}

        day = row['DAY'].strip()
        if day not in timetable[current_branch]:
            timetable[current_branch][day] = {}

        for time_slot in time_slots:
            # Check for NaN, empty strings, or placeholder whitespace
            if pd.notna(row[time_slot]) and str(row[time_slot]).strip():
                # Split the cell content, e.g., "Subject / Room"
                parts = str(row[time_slot]).split(' / ')
                subject = parts[0].strip()
                room = parts[1].strip() if len(parts) > 1 else ""

                # Create and add the entry
                timetable[current_branch][day][time_slot] = {
                    "subject": subject,
                    "room": room
                }

    return timetable

def compare_timetables(json_tt, csv_tt):
    """
    Compares two timetable dictionaries and returns a report of any discrepancies.
    """
    discrepancies = {
        "mismatches": [],
        "missing_in_file": [],
        "missing_in_json": []
    }

    all_branches = set(json_tt.keys()) | set(csv_tt.keys())

    for branch in sorted(list(all_branches)):
        json_branch_data = json_tt.get(branch, {})
        csv_branch_data = csv_tt.get(branch, {})
        
        all_days = set(json_branch_data.keys()) | set(csv_branch_data.keys())

        for day in sorted(list(all_days)):
            json_day_data = json_branch_data.get(day, {})
            csv_day_data = csv_branch_data.get(day, {})

            all_times = set(json_day_data.keys()) | set(csv_day_data.keys())

            for time in sorted(list(all_times)):
                json_entry = json_day_data.get(time)
                csv_entry = csv_day_data.get(time)

                if json_entry and not csv_entry:
                    discrepancies["missing_in_file"].append(
                        f"[{branch} | {day} | {time}]: JSON has '{json_entry['subject']}', but file has no entry."
                    )
                elif not json_entry and csv_entry:
                    discrepancies["missing_in_json"].append(
                        f"[{branch} | {day} | {time}]: File has '{csv_entry['subject']}', but JSON has no entry."
                    )
                elif json_entry and csv_entry:
                    if json_entry['subject'] != csv_entry['subject'] or json_entry['room'] != csv_entry['room']:
                        discrepancies["mismatches"].append(
                            f"[{branch} | {day} | {time}]: JSON has '{json_entry['subject']}/{json_entry['room']}' but file has '{csv_entry['subject']}/{csv_entry['room']}'."
                        )
    return discrepancies

def main():
    """
    Main function to execute the timetable verification.
    """
    # --- Step 1: Update your file paths here ---
    json_file_path = 'timetable_5th_filled.json'
    core_csv_path = '1.csv'
    
    # --- Step 2: Load the files ---
    try:
        with open(json_file_path, 'r') as f:
            json_data = json.load(f)
        
        core_df = pd.read_csv(core_csv_path)
    except FileNotFoundError as e:
        print(f"Error: Could not find a file. Please check your file paths. Details: {e}")
        return
    except Exception as e:
        print(f"An error occurred while reading the files: {e}")
        return

    # --- Step 3: Process and compare the timetables ---
    print("Reading and processing data from Core CSV file...")
    csv_timetable = create_timetable_from_csv(core_df)
    
    print("Comparing files...")
    discrepancies = compare_timetables(json_data, csv_timetable)

    # --- Step 4: Report the results ---
    print("-" * 50)
    if not any(discrepancies.values()):
        print("✅ Success! The JSON data is an exact match of the data in the Core CSV file.")
    else:
        print("❌ Verification Failed. The JSON and Core CSV files do not match.")
        
        if discrepancies["mismatches"]:
            print("\n## Mismatched Entries")
            for item in discrepancies["mismatches"]:
                print(f"- {item}")
        
        if discrepancies["missing_in_file"]:
            print("\n## Entries Missing in Core CSV File (but present in JSON)")
            for item in discrepancies["missing_in_file"]:
                print(f"- {item}")

        if discrepancies["missing_in_json"]:
            print("\n## Entries Missing in JSON (but present in Core CSV file)")
            for item in discrepancies["missing_in_json"]:
                print(f"- {item}")
    print("-" * 50)

if __name__ == "__main__":
    main()