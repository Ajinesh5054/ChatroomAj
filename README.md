# LinkChat – Real-Time Chatroom
Python Flask + Flask-SocketIO real-time chatroom.

Features: account signup/login/logout, secure password hashing, profiles,
public/private rooms, unique invitation URLs, host membership, real-time
WebSocket chat, message history, presence notifications, direct messages,
responsive UI, SQLite by default and PostgreSQL via DATABASE_URL.

Render build: `pip install -r requirements.txt`
Render start: `gunicorn --worker-class gthread --threads 100 --bind 0.0.0.0:$PORT app:app`
