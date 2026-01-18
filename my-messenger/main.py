import os
import datetime
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nexus_secret_key_2026'

# Твоя строка подключения к MongoDB
MONGO_URI = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URI)
db = client['messenger_db']

socketio = SocketIO(app, cors_allowed_origins="*")

# --- Помощник для получения пользователя ---
def get_user():
    if 'user_id' in session:
        return db.users.find_one({"_id": ObjectId(session['user_id'])})
    return None

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    user = get_user()
    return render_template('index.html', user=user)

@app.route('/login')
def login_page():
    return '''<body style="background:#0f172a;color:white;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;">
    <form action="/api/login" method="post" style="display:flex;flex-direction:column;gap:10px;width:300px;">
        <h2>Вход в Nexus</h2>
        <input name="username" placeholder="Username" style="padding:10px;border-radius:5px;border:none;">
        <input name="password" type="password" placeholder="Password" style="padding:10px;border-radius:5px;border:none;">
        <button type="submit" style="padding:10px;background:#3b82f6;color:white;border:none;border-radius:5px;cursor:pointer;">Войти</button>
        <a href="/register" style="color:#60a5fa;text-align:center;font-size:12px;">Нет аккаунта? Регистрация</a>
    </form></body>'''

@app.route('/register')
def register_page():
    return '''<body style="background:#0f172a;color:white;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;">
    <form action="/api/register" method="post" style="display:flex;flex-direction:column;gap:10px;width:300px;">
        <h2>Создать аккаунт</h2>
        <input name="username" placeholder="Придумайте @username" style="padding:10px;border-radius:5px;border:none;">
        <input name="password" type="password" placeholder="Пароль" style="padding:10px;border-radius:5px;border:none;">
        <button type="submit" style="padding:10px;background:#10b981;color:white;border:none;border-radius:5px;cursor:pointer;">Зарегистрироваться</button>
    </form></body>'''

# --- API Эндпоинты ---
@app.route('/api/register', methods=['POST'])
def api_register():
    username = request.form.get('username')
    password = request.form.get('password')
    if db.users.find_one({"username": username}):
        return "Username занят", 400
    user_id = db.users.insert_one({
        "username": username,
        "display_name": username,
        "password": generate_password_hash(password),
        "avatar": f"https://ui-avatars.com/api/?name={username}",
        "bio": "Nexus user",
        "theme": "dark",
        "is_banned": False
    }).inserted_id
    session['user_id'] = str(user_id)
    return redirect(url_for('index'))

@app.route('/api/login', methods=['POST'])
def api_login():
    user = db.users.find_one({"username": request.form.get('username')})
    if user and check_password_hash(user['password'], request.form.get('password')):
        session['user_id'] = str(user['_id'])
        return redirect(url_for('index'))
    return "Ошибка входа", 401

# --- Socket.IO: Реальное время и Админка ---
@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)
    # Загрузка истории (40-50 сообщений)
    messages = list(db.messages.find({"room": room}).sort("ts", -1).limit(50))
    for m in reversed(messages):
        m['_id'] = str(m['_id'])
        m['sender_id'] = str(m['sender_id'])
        emit('new_message', m)

@socketio.on('send_msg')
def handle_msg(data):
    user = get_user()
    room_id = data.get('room', 'general')
    
    # Проверка прав (Бан/Мут)
    group = db.groups.find_one({"_id": ObjectId(room_id)}) if room_id != 'general' else None
    if user.get('is_banned'): return
    if group and (ObjectId(user['_id']) in group.get('muted', [])):
        emit('error', {'msg': 'Вы в муте'})
        return

    msg_obj = {
        "room": room_id,
        "sender_id": str(user['_id']),
        "sender_name": user['display_name'],
        "sender_avatar": user['avatar'],
        "text": data.get('text'),
        "type": data.get('type', 'text'), # text, file, voice, video_circle
        "file_url": data.get('file_url', ''),
        "reactions": {},
        "ts": datetime.datetime.utcnow().isoformat()
    }
    res = db.messages.insert_one(msg_obj)
    msg_obj['_id'] = str(res.inserted_id)
    emit('new_message', msg_obj, room=room_id)

@socketio.on('delete_msg')
def delete_msg(data):
    user = get_user()
    msg = db.messages.find_one({"_id": ObjectId(data['msg_id'])})
    # Право удаления: Автор или Владелец/Админ
    if str(msg['sender_id']) == str(user['_id']):
        db.messages.delete_one({"_id": ObjectId(data['msg_id'])})
        emit('msg_deleted', data['msg_id'], room=msg['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
