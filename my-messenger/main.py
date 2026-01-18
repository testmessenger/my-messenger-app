import os
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-key-123' # В будущем вынеси в переменные Render

# Подключение к твоей базе
MONGO_URI = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URI)
db = client['messenger_db']

socketio = SocketIO(app, cors_allowed_origins="*", max_content_length=16 * 1024 * 1024) # 16MB limit

# --- Middlewares & Helpers ---
def get_current_user():
    if 'user_id' in session:
        return db.users.find_one({"_id": ObjectId(session['user_id'])})
    return None

# --- Роуты Авторизации ---
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if db.users.find_one({"username": data['username']}):
        return jsonify({"error": "Username уже занят"}), 400
    
    user_id = db.users.insert_one({
        "username": data['username'],
        "display_name": data['username'],
        "password": generate_password_hash(data['password']),
        "avatar": "https://ui-avatars.com/api/?name=" + data['username'],
        "bio": "",
        "theme": "dark",
        "created_at": datetime.datetime.utcnow()
    }).inserted_id
    return jsonify({"success": True})

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = db.users.find_one({"username": data['username']})
    if user and check_password_hash(user['password'], data['password']):
        session['user_id'] = str(user['_id'])
        return jsonify({"success": True})
    return jsonify({"error": "Неверные данные"}), 401

# --- Работа с Профилем ---
@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    user = get_current_user()
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    db.users.update_one({"_id": user['_id']}, {"$set": {
        "display_name": data.get('display_name', user['display_name']),
        "bio": data.get('bio', user['bio']),
        "avatar": data.get('avatar', user['avatar']),
        "theme": data.get('theme', user['theme'])
    }})
    return jsonify({"success": True})

# --- Группы и Администрирование ---
@app.route('/api/groups/create', methods=['POST'])
def create_group():
    user = get_current_user()
    data = request.json
    group_id = db.groups.insert_one({
        "title": data['title'],
        "owner_id": user['_id'],
        "admins": [user['_id']],
        "members": [user['_id']],
        "muted": [],
        "banned": [],
        "created_at": datetime.datetime.utcnow()
    }).inserted_id
    return jsonify({"group_id": str(group_id)})

# --- Socket.IO события ---
@socketio.on('join_chat')
def handle_join(data):
    room = data['group_id']
    join_room(room)
    
    # Подгрузка истории (последние 50 сообщений)
    messages = list(db.messages.find({"group_id": room}).sort("timestamp", -1).limit(50))
    for m in reversed(messages):
        m['_id'] = str(m['_id'])
        m['sender_id'] = str(m['sender_id'])
        emit('new_message', m)

@socketio.on('send_msg')
def handle_msg(data):
    user = get_current_user()
    group = db.groups.find_one({"_id": ObjectId(data['group_id'])})
    
    # Проверка на бан и мут
    if user['_id'] in group.get('banned', []): return
    if user['_id'] in group.get('muted', []):
        emit('error', {'msg': 'Вы в муте'})
        return

    msg_obj = {
        "group_id": data['group_id'],
        "sender_id": user['_id'],
        "sender_name": user['display_name'],
        "sender_avatar": user['avatar'],
        "text": data.get('text', ''),
        "type": data.get('type', 'text'), # text, file, voice, video_note
        "file_url": data.get('file_url', ''),
        "reactions": {},
        "timestamp": datetime.datetime.utcnow()
    }
    res = db.messages.insert_one(msg_obj)
    msg_obj['_id'] = str(res.inserted_id)
    msg_obj['sender_id'] = str(user['_id'])
    
    emit('new_message', msg_obj, room=data['group_id'])

@socketio.on('delete_message')
def delete_msg(data):
    user = get_current_user()
    msg = db.messages.find_one({"_id": ObjectId(data['msg_id'])})
    group = db.groups.find_one({"_id": ObjectId(msg['group_id'])})
    
    # Права: автор сообщения ИЛИ админ/владелец группы
    is_admin = user['_id'] in group.get('admins', []) or user['_id'] == group['owner_id']
    if str(msg['sender_id']) == str(user['_id']) or is_admin:
        db.messages.delete_one({"_id": ObjectId(data['msg_id'])})
        emit('message_deleted', {'msg_id': data['msg_id']}, room=msg['group_id'])

@socketio.on('add_reaction')
def react(data):
    # data: {msg_id, emoji}
    db.messages.update_one(
        {"_id": ObjectId(data['msg_id'])},
        {"$inc": {f"reactions.{data['emoji']}": 1}}
    )
    emit('update_reactions', data, room=data['group_id'])

if __name__ == '__main__':
    socketio.run(app, debug=True)
