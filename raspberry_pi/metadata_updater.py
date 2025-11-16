#!/usr/bin/env python3
"""
Reads camera metadata stream and writes only the latest value to /tmp/camera_metadata.json
Updates every 1 second
"""
import time
import json
import re

STREAM_FILE = '/tmp/camera_metadata_stream.txt'
OUTPUT_FILE = '/var/tmp/camera_metadata.json'

print("📷 Camera metadata updater started")
print(f"Reading from: {STREAM_FILE}")
print(f"Writing to: {OUTPUT_FILE}")

while True:
    try:
        # Efficiently read only the last 10KB from the stream file
        with open(STREAM_FILE, 'rb') as f:
            f.seek(0, 2)  # Seek to end
            file_size = f.tell()
            read_size = min(10240, file_size)  # Read last 10KB max
            f.seek(max(0, file_size - read_size))
            content = f.read().decode('utf-8', errors='ignore')

        # Find all JSON objects using regex (handles multi-line pretty-print)
        # Look for pattern: },\n{ or just trailing }
        objects = re.split(r'\},\s*\n\s*\{', content)

        if objects:
            # Get the last object
            last_obj = objects[-1]

            # Fix if it's missing opening/closing braces
            if not last_obj.strip().startswith('{'):
                last_obj = '{' + last_obj
            if not last_obj.strip().endswith('}'):
                last_obj = last_obj + '}'

            try:
                # Parse and write the latest metadata
                metadata = json.loads(last_obj)
                with open(OUTPUT_FILE, 'w') as out:
                    json.dump(metadata, out)
            except json.JSONDecodeError as e:
                # If parsing fails, try to get the second-to-last which should be complete
                if len(objects) > 1:
                    try:
                        prev_obj = '{' + objects[-2] + '}'
                        metadata = json.loads(prev_obj)
                        with open(OUTPUT_FILE, 'w') as out:
                            json.dump(metadata, out)
                    except:
                        pass

        time.sleep(1)

    except FileNotFoundError:
        print(f"Waiting for {STREAM_FILE}...")
        time.sleep(2)
    except KeyboardInterrupt:
        print("\n👋 Stopping metadata updater")
        break
    except Exception as e:
        print(f"✗ Error: {e}")
        time.sleep(2)
