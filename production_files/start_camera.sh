#!/bin/bash
# Camera server startup wrapper with proper cleanup

set -e

CAMERA_PID=""
PYTHON_PID=""

# Cleanup function
cleanup() {
    echo "Received shutdown signal, cleaning up..."
    
    # Kill Python process group
    if [ -n "$PYTHON_PID" ]; then
        echo "Stopping camera server (PID: $PYTHON_PID)..."
        kill -TERM "$PYTHON_PID" 2>/dev/null || true
        
        # Wait up to 10 seconds for graceful shutdown
        for i in {1..10}; do
            if ! kill -0 "$PYTHON_PID" 2>/dev/null; then
                echo "Camera server stopped gracefully"
                exit 0
            fi
            sleep 1
        done
        
        # Force kill if still running
        echo "Force killing camera server..."
        kill -9 "$PYTHON_PID" 2>/dev/null || true
    fi
    
    # Kill any remaining python3 processes running camera_server.py
    pkill -9 -f "camera_server.py" 2>/dev/null || true
    
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT SIGQUIT

# Start camera server
cd /home/binhex
python3 camera_server.py &
PYTHON_PID=$!

echo "Camera server started with PID: $PYTHON_PID"

# Wait for process
wait $PYTHON_PID
EXIT_CODE=$?

echo "Camera server exited with code: $EXIT_CODE"
exit $EXIT_CODE
