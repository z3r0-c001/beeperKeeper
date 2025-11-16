#!/bin/bash
# BEEPER KEEPER v2.0 - USB Camera Capture Script
# Generic USB webcam detection - works with ANY USB camera

# Auto-detect USB webcam video device (exclude CSI/platform cameras)
USB_VIDEO_DEV=""
USB_VIDEO_NAME=""
for dev in /dev/video*; do
    if [ -c "$dev" ]; then
        # Get device info
        dev_info=$(v4l2-ctl --device="$dev" --info 2>/dev/null)

        # Skip if not a valid device
        [ -z "$dev_info" ] && continue

        # Skip CSI camera (mmal/bcm2835 driver - Raspberry Pi camera module)
        if echo "$dev_info" | grep -qi "mmal\|bcm2835"; then
            continue
        fi

        # Check if it's a capture device
        if ! echo "$dev_info" | grep -qi "capture"; then
            continue
        fi

        # Check if it's a USB device
        if echo "$dev_info" | grep -qi "usb"; then
            USB_VIDEO_DEV="$dev"
            USB_VIDEO_NAME=$(echo "$dev_info" | grep "Card type" | cut -d':' -f2 | xargs)
            [ -z "$USB_VIDEO_NAME" ] && USB_VIDEO_NAME="USB Camera"
            break
        fi
    fi
done

# Auto-detect USB webcam audio card (any USB audio capture device)
USB_AUDIO_DEV=""
USB_AUDIO_CARD_NAME=""
USB_AUDIO_CARD_NUM=""
while IFS= read -r line; do
    # Look for USB audio devices
    if echo "$line" | grep -qi "USB"; then
        # Extract card number
        card_num=$(echo "$line" | sed -n 's/.*card \([0-9]\+\).*/\1/p')
        # Extract card name (between square brackets)
        card_name=$(echo "$line" | sed -n 's/.*\[\(.*\)\].*/\1/p')

        if [ -n "$card_num" ]; then
            USB_AUDIO_CARD_NUM="$card_num"
            USB_AUDIO_CARD_NAME="$card_name"
            USB_AUDIO_DEV="dsnoop_usb"  # Use generic ALSA dsnoop for shared access
            break
        fi
    fi
done < <(arecord -l 2>/dev/null)

# Log detected devices with details
if [ -n "$USB_VIDEO_DEV" ]; then
    echo "[USB Camera v2.0] ✓ Video: $USB_VIDEO_DEV ($USB_VIDEO_NAME)" >&2
else
    echo "[USB Camera v2.0] ✗ No USB video device found" >&2
fi

if [ -n "$USB_AUDIO_DEV" ]; then
    echo "[USB Camera v2.0] ✓ Audio: Card $USB_AUDIO_CARD_NUM [$USB_AUDIO_CARD_NAME] → $USB_AUDIO_DEV" >&2
else
    echo "[USB Camera v2.0] ⚠ No USB audio device found - will run video-only" >&2
fi

# Exit if no video device found
if [ -z "$USB_VIDEO_DEV" ]; then
    echo "[USB Camera v2.0] ERROR: No USB camera detected. Please check connections." >&2
    exit 1
fi

# Decide whether to run with or without audio
USE_AUDIO=false
if [ -n "$USB_AUDIO_DEV" ]; then
    USE_AUDIO=true
fi

# 800x600 @ 15fps MJPEG → H.264 Baseline (+ AAC Audio if available)
# OPTIMIZED FOR USB 2.0: Logitech C270 is USB 2.0 (bcdUSB 2.00) - max 480 Mbps
# 800x600 = 33% more pixels than 640x480, 56% fewer than 720p
# 15fps provides smooth motion within USB 2.0 bandwidth constraints
# Estimated bandwidth: ~15-18 Mbps video + 1.5 Mbps audio = ~20 Mbps total

if [ "$USE_AUDIO" = true ]; then
    # WITH AUDIO: 800x600@15fps MJPEG → H.264 Baseline + AAC
    # AAC audio for HLS compatibility (Opus doesn't work reliably with HLS.js)
    # Balanced resolution/framerate for USB 2.0 cameras
    echo "[USB Camera v2.0] Starting stream WITH audio (800x600@15fps, USB 2.0, AAC for HLS)" >&2
    exec ffmpeg \
        -f v4l2 -input_format mjpeg -video_size 800x600 -framerate 15 -i "$USB_VIDEO_DEV" \
        -f alsa -sample_rate 48000 -channels 1 -i "$USB_AUDIO_DEV" \
        -c:v libx264 -profile:v baseline -level 3.1 -preset ultrafast -tune zerolatency \
        -pix_fmt yuv420p \
        -crf 26 -maxrate 1500k -bufsize 1500k -g 30 \
        -c:a aac -b:a 64k -ar 48000 \
        -f rtsp -rtsp_transport tcp rtsp://localhost:8554/usb_camera
else
    # VIDEO ONLY: 800x600@15fps MJPEG → H.264 Baseline
    # Balanced resolution/framerate for USB 2.0 cameras
    echo "[USB Camera v2.0] Starting stream WITHOUT audio (800x600@15fps, USB 2.0)" >&2
    exec ffmpeg \
        -f v4l2 -input_format mjpeg -video_size 800x600 -framerate 15 -i "$USB_VIDEO_DEV" \
        -c:v libx264 -profile:v baseline -level 3.1 -preset ultrafast -tune zerolatency \
        -pix_fmt yuv420p \
        -crf 26 -maxrate 1500k -bufsize 1500k -g 30 \
        -f rtsp -rtsp_transport tcp rtsp://localhost:8554/usb_camera
fi
