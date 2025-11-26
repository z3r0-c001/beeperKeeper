#!/usr/bin/env python3
"""
BeeperKeeper Flask Application Entry Point

Run with: python3 run.py
Or via systemd service: flask-app.service
"""
import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import socketio


def main():
    """Main entry point"""
    print("\n" + "=" * 60)
    print("BEEPER KEEPER v2.0 - Refactored Edition")
    print("=" * 60)

    # Create app
    app = create_app()

    print("\nStarting web server on http://0.0.0.0:8080")
    print("HLS streams available via Flask proxy routes")
    print("WebSocket streaming enabled on /announce_stream namespace")
    print("\nPress Ctrl+C to stop\n")

    try:
        socketio.run(app, host='0.0.0.0', port=8080, debug=False)
    except (KeyboardInterrupt, SystemExit):
        # Shutdown scheduler if running
        scheduler = app.config.get('scheduler')
        if scheduler:
            scheduler.shutdown()
            print("\nScheduler stopped")
        print("Server stopped")


if __name__ == '__main__':
    main()
