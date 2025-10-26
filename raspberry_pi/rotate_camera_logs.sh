#!/bin/bash
# Rotate camera metadata stream log when it exceeds 10MB
# Add to crontab: */5 * * * * /opt/beeperKeeper/rotate_camera_logs.sh

STREAM_FILE="/tmp/camera_metadata_stream.txt"
MAX_SIZE_MB=10
MAX_SIZE_BYTES=$((MAX_SIZE_MB * 1024 * 1024))

if [ -f "$STREAM_FILE" ]; then
    FILE_SIZE=$(stat -f%z "$STREAM_FILE" 2>/dev/null || stat -c%s "$STREAM_FILE" 2>/dev/null)

    if [ "$FILE_SIZE" -gt "$MAX_SIZE_BYTES" ]; then
        echo "$(date): Rotating camera metadata log (${FILE_SIZE} bytes)"

        # Keep last 1MB, discard the rest
        tail -c 1048576 "$STREAM_FILE" > "${STREAM_FILE}.tmp"
        mv "${STREAM_FILE}.tmp" "$STREAM_FILE"

        echo "$(date): Log rotated, new size: $(stat -f%z "$STREAM_FILE" 2>/dev/null || stat -c%s "$STREAM_FILE" 2>/dev/null) bytes"
    fi
fi
