#!/bin/bash
# CSI Camera - 1296x972 full FOV, 2s GOP
exec rpicam-vid     --timeout 0     --width 1296     --height 972     --framerate 30     --codec h264     --profile baseline     --bitrate 1500000     --intra 60     --keypress 0     --signal 0     --inline     --flush     --nopreview     -o - | ffmpeg     -fflags +genpts     -use_wallclock_as_timestamps 1     -i pipe:0     -c:v copy     -f rtsp     -rtsp_transport tcp     rtsp://localhost:8554/csi_camera
