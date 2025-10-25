#!/bin/bash
# BEEPER KEEPER 10000 - Automatic Device Detection Script
# Detects USB webcam video device and audio card dynamically

# Find USB webcam (Logitech) video device
USB_VIDEO_DEV=""
for dev in /dev/video*; do
    if [ -c "$dev" ]; then
        # Check if this is a capture device (not metadata)
        caps=$(v4l2-ctl --device="$dev" --all 2>/dev/null | grep -i "Video Capture")
        if [ -n "$caps" ]; then
            # Check if it's a USB device (Logitech)
            info=$(v4l2-ctl --device="$dev" --info 2>/dev/null)
            if echo "$info" | grep -qi "usb"; then
                USB_VIDEO_DEV="$dev"
                break
            fi
        fi
    fi
done

# Find USB webcam audio card
USB_AUDIO_DEV=""
while IFS= read -r line; do
    # Look for Logitech USB card
    if echo "$line" | grep -qi "0x46d"; then
        # Extract card number (format: "card 1: ...")
        card_num=$(echo "$line" | sed -n 's/.*card \([0-9]\+\).*/\1/p')
        USB_AUDIO_DEV="hw:${card_num},0"
        break
    fi
done < <(arecord -l 2>/dev/null)

# Check for errors
if [ -z "$USB_VIDEO_DEV" ]; then
    echo "ERROR: USB video device not found" >&2
    return 1 2>/dev/null || exit 1
fi

if [ -z "$USB_AUDIO_DEV" ]; then
    echo "ERROR: USB audio device not found" >&2
    return 1 2>/dev/null || exit 1
fi

# Export for use by MediaMTX (as export statements for sourcing)
export USB_VIDEO_DEV
export USB_AUDIO_DEV

# Also print for debugging
echo "Detected USB_VIDEO_DEV=${USB_VIDEO_DEV}" >&2
echo "Detected USB_AUDIO_DEV=${USB_AUDIO_DEV}" >&2
