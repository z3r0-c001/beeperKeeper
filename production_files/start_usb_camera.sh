#!/bin/bash
# BEEPER KEEPER 10000 - USB Camera Auto-Start Script
# Automatically detects USB webcam video and audio devices and starts ffmpeg streaming

# Find USB webcam video device
USB_VIDEO_DEV=""
for dev in /dev/video*; do
    if [ -c "$dev" ]; then
        # Check if this is a capture device (not metadata)
        if v4l2-ctl --device="$dev" --all 2>/dev/null | grep -q "Video Capture"; then
            # Check if it's a USB device (Logitech)
            if v4l2-ctl --device="$dev" --info 2>/dev/null | grep -qi "usb"; then
                USB_VIDEO_DEV="$dev"
                break
            fi
        fi
    fi
done

# Find USB webcam audio card
USB_AUDIO_DEV=""
while IFS= read -r line; do
    # Look for Logitech USB card (vendor ID 0x46d)
    if echo "$line" | grep -qi "0x46d"; then
        # Extract card number (format: "card 1: ...")
        card_num=$(echo "$line" | sed -n 's/.*card \([0-9]\+\).*/\1/p')
        USB_AUDIO_DEV="hw:${card_num},0"
        break
    fi
done < <(arecord -l 2>/dev/null)

# Log detection results
echo "[USB Camera] Detected video device: ${USB_VIDEO_DEV:-NONE}" >&2
echo "[USB Camera] Detected audio device: ${USB_AUDIO_DEV:-NONE}" >&2

# Check if devices were found
if [ -z "$USB_VIDEO_DEV" ]; then
    echo "[USB Camera] ERROR: USB video device not found" >&2
    exit 1
fi

if [ -z "$USB_AUDIO_DEV" ]; then
    echo "[USB Camera] ERROR: USB audio device not found" >&2
    exit 1
fi

# Start ffmpeg with detected devices - USING GITHUB WORKING CONFIG FORMAT
exec ffmpeg \
    -f v4l2 -input_format mjpeg -video_size 640x480 -framerate 15 -i "$USB_VIDEO_DEV" \
    -f alsa -channels 1 -sample_rate 16000 -i "$USB_AUDIO_DEV" \
    -map 0:v:0 -map 1:a:0 \
    -c:v libvpx -quality realtime -speed 8 -threads 2 -b:v 500k -g 15 \
    -c:a libopus -b:a 32k \
    -f rtsp rtsp://localhost:8554/usb_camera
