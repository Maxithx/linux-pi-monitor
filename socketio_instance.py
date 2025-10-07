# === socketio_instance.py ===
# This file creates a single shared SocketIO instance for use across the app.
# It is imported in app.py and also used in terminal.py for real-time WebSocket communication.

from flask_socketio import SocketIO

# Allow all CORS origins (e.g. for accessing the app from localhost in browser)
socketio = SocketIO(cors_allowed_origins="*")
