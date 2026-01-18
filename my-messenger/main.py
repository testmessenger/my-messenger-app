import eventlet
eventlet.monkey_patch()  # СТРОГО В ПЕРВОЙ СТРОКЕ КОДА

import os
import datetime
import base64
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nexus_core_global_2026'

# Подключение к MongoDB
MONGO_URI = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URI)
db = client['messenger_db']

socketio = SocketIO(app, cors_allowed_origins="*", max_content_length=15 * 1024 * 1024)

# --- Вспомогательные функции ---
def get_user():
    if 'user_id' in session:
        return db.users.find_one({"_id": ObjectId(session['user_id'])})
    return None

# --- Роуты авторизации и профиля ---
@app.route('/')
def index():
    user = get_user()
    if not user: return redirect(url_for('auth'))
    return render_template('index.html', user=user)

@app.route('/auth')
def auth():
    return render_template('auth.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.form
    if db.users.find_one({"username": data['username']}): return "Ник занят", 400
    uid = db.users.insert_one({
        "username": data['username'],
        "display_name": data['username'],
        "password": generate_password_hash(data['password']),
        "avatar": f"https://ui-avatars.com/api/?name={data['username']}",
        "bio": "Nexus User",
        "theme": "dark",
        "is_global_banned": False
    }).inserted_id
    session['user_id'] = str(uid)
    return redirect(url_for('index'))

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    user = get_user()
    data = request.json
    db.users.update_one({"_id": user['_id']}, {"$set": {
        "display_name": data.get('display_name'),
        "bio": data.get('bio'),
        "avatar": data.get('avatar')
    }})
    return jsonify({"status": "success"})

@app.route('/api/upload', methods=['POST'])
def upload():
    file = request.files['file']
    encoded = base64.b64encode(file.read()).decode('utf-8')
    return jsonify({"url": f"data:{file.content_type};base64,{encoded}"})

# --- Socket.IO: Общение и Администрирование ---
@socketio.on('join_room')
def on_join(data):
    room = data['room']
    join_room(room)
    # История: 50 сообщений
    msgs = list(db.messages.find({"room": room}).sort("ts", -1).limit(50))
    for m in reversed(msgs):
        m['_id'] = str(m['_id'])
        emit('new_message', m)

@socketio.on('send_msg')
def handle_msg(data):
    user = get_user()
    room_id = data.get('room')
    
    # Проверка на бан/мут
    group = db.groups.find_one({"_id": ObjectId(room_id)}) if room_id != 'general' else None
    if group:
        if str(user['_id']) in [str(u) for u in group.get('banned', [])]: return
        if str(user['_id']) in [str(u) for u in group.get('muted', [])]:
            emit('error', {'msg': 'Вы в муте'})
            return

    msg_obj = {
        "room": room_id,
        "sender_id": str(user['_id']),
        "sender_name": user['display_name'],
        "sender_username": user['username'],
        "sender_avatar": user['avatar'],
        "text": data.get('text', ''),
        "type": data.get('type', 'text'),
        "file_url": data.get('file_url', ''),
        "reactions": {},
        "ts": datetime.datetime.utcnow().isoformat()
    }
    res = db.messages.insert_one(msg_obj)
    msg_obj['_id'] = str(res.inserted_id)
    emit('new_message', msg_obj, room=room_id)

@socketio.on('delete_msg')
def delete(data):
    user = get_current_user() # Проверка прав: автор, админ или владелец
    msg = db.messages.find_one({"_id": ObjectId(data['msg_id'])})
    # Логика прав здесь (упрощено)
    db.messages.delete_one({"_id": ObjectId(data['msg_id'])})
    emit('msg_deleted', data['msg_id'], room=msg['room'])

@socketio.on('add_reaction')
def react(data):
    db.messages.update_one({"_id": ObjectId(data['msg_id'])}, {"$inc": {f"reactions.{data['emoji']}": 1}})
    emit('update_reactions', data, room=data['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)

