import csv
import json

def convert_csv_to_json(csv_file_path, json_file_path):
    """
    Convert CSV file to JSON format with roll numbers as keys and sections as values.
    
    Args:
        csv_file_path: Path to input CSV file
        json_file_path: Path to output JSON file
    """
    # Dictionary to store the data with roll_no as key
    roll_to_section = {}
    
    # Read CSV file
    with open(csv_file_path, 'r', encoding='utf-8-sig') as csv_file:
        csv_reader = csv.reader(csv_file)
        
        for row in csv_reader:
            if len(row) >= 2:
                roll_no = row[0].strip()
                section = row[1].strip()
                
                # Add roll number as key and section as value
                roll_to_section[roll_no] = section
    
    # Write to JSON file
    with open(json_file_path, 'w') as json_file:
        json.dump(roll_to_section, json_file, indent=4)
    
    print(f"Successfully converted {csv_file_path} to {json_file_path}")
    print(f"Total students: {len(roll_to_section)}")
    
    # Count sections
    sections = {}
    for section in roll_to_section.values():
        sections[section] = sections.get(section, 0) + 1
    print(f"Total sections: {len(sections)}")

if __name__ == "__main__":
    # File paths
    csv_file = r"c:\Users\KIIT0001\Downloads\rollno\4th_sem_roll.csv"
    json_file = r"c:\Users\KIIT0001\Downloads\rollno\4th_sem_roll.json"
    
    # Convert CSV to JSON
    convert_csv_to_json(csv_file, json_file)
