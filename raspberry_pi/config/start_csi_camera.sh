#!/bin/bash
# BEEPER KEEPER v2.0 - CSI Camera Capture Script
# OV5647 Camera Module @ 1920x1080 30fps with hardware H.264 encoding

echo "[CSI Camera v2.0] Starting OV5647 camera stream..." >&2

# Use rpicam-vid (libcamera) for Pi 4 with hardware H.264 encoding
# Output to stdout, then pipe to ffmpeg for RTSP publishing
exec rpicam-vid \
    --timeout 0 \
    --width 1920 \
    --height 1080 \
    --framerate 30 \
    --codec h264 \
    --profile baseline \
    --bitrate 2000000 \
    --keypress 0 \
    --signal 0 \
    --inline \
    --flush \
    --nopreview \
    -o - | \
ffmpeg \
    -use_wallclock_as_timestamps 1 \
    -i pipe:0 \
    -c:v copy \
    -f rtsp \
    -rtsp_transport tcp \
    rtsp://localhost:8554/csi_camera
