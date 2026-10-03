import csv
from pycomm3 import LogixDriver

def read_single_tag(plc_ip, tag_name):
    try:
        with LogixDriver(plc_ip) as plc:
            print(f"Connected to PLC at {plc_ip}")
            result = plc.read(tag_name)
            if result is not None and result.value is not None:
                print(f"Tag '{tag_name}' value: {result.value}")
                return result.value
            else:
                print(f"Tag '{tag_name}' not found or no value returned.")
                return None
    except Exception as e:
        print(f"Error reading tag '{tag_name}': {e}")
        return None

# Connect to PLC and get all tags
def get_all_plc_tags(plc_ip):
    try:
        # Create connection to PLC
        with LogixDriver(plc_ip) as plc:
            print(f"Connected to PLC at {plc_ip}")
            # Get all tags from PLC
            tags = plc.get_tag_list()
            print(f"Found {len(tags)} tags:")
            # Print all tags with their details
            for tag in tags:
                print(f"Tag: {tag['tag_name']}, Type: {tag['data_type']}, Value: {tag.get('value', 'N/A')}")
            return tags
    except Exception as e:
        print(f"Error connecting to PLC: {e}")
        return None


if __name__ == "__main__":
    plc_ip_address = "192.168.1.10"  # Replace with your PLC IP
    #all_tags = get_all_plc_tags(plc_ip_address)

    # Example: Read a single tag (replace 'MyStructTag' with your tag name)
    single_tag_value = read_single_tag(plc_ip_address, 'TRAYDATA[1]')
    print(f"Single tag value: {single_tag_value}")

'''
if __name__ == "__main__":
   # plc_ip_address = "169.7.229.178"  # Replace PLC IP
    plc_ip_address = "192.168.1.10"  
    all_tags = get_all_plc_tags(plc_ip_address)
    if all_tags:
        # Save to CSV file
        with open('plc_tags1.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Tag', 'Name', 'Data_Type']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for tag in all_tags:
                writer.writerow({
                    'Tag': tag['tag_name'],
                    'Name': tag['tag_name'],
                    'Data_Type': tag['data_type']
                })
        print(f"\nTags saved to 'plc_tags.csv' with {len(all_tags)} entries.")
'''