#!/bin/bash
# Start rpicam-vid with metadata output to file
# Video goes to stdout for ffmpeg, metadata goes to file

rpicam-vid \
  --codec h264 \
  --width 800 \
  --height 600 \
  --framerate 15 \
  --inline \
  --timeout 0 \
  --metadata /tmp/camera_metadata_stream.txt \
  --metadata-format json \
  -o - | \
ffmpeg -f h264 -i - -c:v copy -f rtsp rtsp://localhost:8554/csi_camera
