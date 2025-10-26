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

# 640x480 @ 10fps YUYV → H.264 with Opus audio (ultra low latency optimized)
exec ffmpeg \
    -f v4l2 -input_format yuyv422 -video_size 640x480 -framerate 10 -i "$USB_VIDEO_DEV" \
    -f alsa -channels 1 -sample_rate 48000 -i "$USB_AUDIO_DEV" \
    -fflags nobuffer -flags low_delay -strict experimental \
    -c:v libx264 -preset ultrafast -tune zerolatency \
    -crf 28 -maxrate 800k -bufsize 400k -g 20 \
    -x264opts bframes=0:keyint=20:min-keyint=20:no-scenecut \
    -c:a libopus -b:a 48k -application voip \
    -f rtsp -rtsp_transport tcp rtsp://localhost:8554/usb_camera
