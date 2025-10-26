#!/bin/bash
# BEEPER KEEPER v2.0 - USB Camera Capture Script
# Logitech C270 @ 720p 30fps with audio

# Auto-detect USB webcam video device
USB_VIDEO_DEV=""
for dev in /dev/video*; do
    if [ -c "$dev" ]; then
        if v4l2-ctl --device="$dev" --all 2>/dev/null | grep -q "Video Capture"; then
            if v4l2-ctl --device="$dev" --info 2>/dev/null | grep -qi "usb"; then
                USB_VIDEO_DEV="$dev"
                break
            fi
        fi
    fi
done

# Auto-detect USB webcam audio card
USB_AUDIO_DEV=""
while IFS= read -r line; do
    if echo "$line" | grep -qi "0x46d"; then
        card_num=$(echo "$line" | sed -n 's/.*card \([0-9]\+\).*/\1/p')
        USB_AUDIO_DEV="hw:${card_num},0"
        break
    fi
done < <(arecord -l 2>/dev/null)

echo "[USB Camera v2.0] Video: ${USB_VIDEO_DEV:-NONE}, Audio: ${USB_AUDIO_DEV:-NONE}" >&2

if [ -z "$USB_VIDEO_DEV" ] || [ -z "$USB_AUDIO_DEV" ]; then
    echo "[USB Camera v2.0] ERROR: Device not found" >&2
    exit 1
fi

# 640x480 @ 15fps MJPEG → H.264 with Opus audio (reduced framerate for Pi 3B+)
exec ffmpeg \
    -f v4l2 -input_format mjpeg -video_size 640x480 -framerate 15 -i "$USB_VIDEO_DEV" \
    -f alsa -channels 1 -sample_rate 48000 -i "$USB_AUDIO_DEV" \
    -c:v libx264 -preset ultrafast -tune zerolatency \
    -crf 28 -maxrate 800k -bufsize 1600k -g 30 \
    -c:a libopus -b:a 48k -application voip \
    -f rtsp rtsp://localhost:8554/usb_camera
