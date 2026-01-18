import eventlet
eventlet.monkey_patch()

import os
import datetime
import base64
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nexus_infinity_full_core_2026'

# --- ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ ---
MONGO_URI = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URI)
db = client['messenger_db']

socketio = SocketIO(app, cors_allowed_origins="*")

def get_user():
    if 'user_id' in session:
        try:
            return db.users.find_one({"_id": ObjectId(session['user_id'])})
        except:
            return None
    return None

# --- ГЛАВНЫЕ СТРАНИЦЫ ---
@app.route('/')
def index():
    user = get_user()
    if not user:
        return redirect(url_for('auth'))
    return render_template('index.html', user=user)

@app.route('/auth')
def auth():
    return render_template('auth.html')

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "short_name": "Nexus",
        "name": "Nexus Global Messenger",
        "icons": [{"src": "https://cdn-icons-png.flaticon.com/512/5968/5968756.png", "sizes": "512x512", "type": "image/png"}],
        "start_url": "/",
        "display": "standalone",
        "background_color": "#020617",
        "theme_color": "#3b82f6"
    })

# --- API АВТОРИЗАЦИИ (ИСПРАВЛЯЕТ ТВОЮ ОШИБКУ 404) ---
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if db.users.find_one({"username": data['username']}):
        return jsonify({"error": "Пользователь уже существует"}), 400
    
    user_id = db.users.insert_one({
        "username": data['username'],
        "password": generate_password_hash(data['password']),
        "display_name": data['username'],
        "avatar": f"https://ui-avatars.com/api/?name={data['username']}&background=random",
        "bio": "Я использую Nexus"
    }).inserted_id
    
    session['user_id'] = str(user_id)
    return jsonify({"status": "ok"})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = db.users.find_one({"username": data['username']})
    if user and check_password_hash(user['password'], data['password']):
        session['user_id'] = str(user['_id'])
        return jsonify({"status": "ok"})
    return jsonify({"error": "Неверный логин или пароль"}), 401

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth'))

# --- API ФУНКЦИЙ ---
@app.route('/api/search')
def search():
    q = request.args.get('q', '')
    users = list(db.users.find({"username": {"$regex": q, "$options": "i"}}, {"password": 0}).limit(5))
    groups = list(db.groups.find({"title": {"$regex": q, "$options": "i"}}).limit(5))
    for x in users + groups: x['_id'] = str(x['_id'])
    return jsonify({"users": users, "groups": groups})

@app.route('/api/profile/save', methods=['POST'])
def save_profile():
    user = get_user()
    if not user: return jsonify({"error": "Unauthorized"}), 401
    db.users.update_one({"_id": user['_id']}, {"$set": {
        "display_name": request.json['name'],
        "bio": request.json['bio']
    }})
    return jsonify({"status": "ok"})

@app.route('/api/groups/create', methods=['POST'])
def create_group():
    user = get_user()
    gid = db.groups.insert_one({
        "title": request.json['title'],
        "owner_id": str(user['_id']),
        "members": [str(user['_id'])],
        "admins": [str(user['_id'])]
    }).inserted_id
    return jsonify({"id": str(gid)})

@app.route('/api/my_chats')
def get_my_chats():
    user = get_user()
    if not user: return jsonify([])
    groups = list(db.groups.find({"members": str(user['_id'])}))
    for g in groups: g['_id'] = str(g['_id'])
    return jsonify(groups)

@app.route('/api/upload', methods=['POST'])
def upload():
    file = request.files['file']
    encoded = base64.b64encode(file.read()).decode('utf-8')
    return jsonify({"url": f"data:{file.content_type};base64,{encoded}"})

# --- SOCKET.IO ---
@socketio.on('join_room')
def on_join(data):
    join_room(data['room'])

@socketio.on('send_msg')
def handle_msg(data):
    user = get_user()
    if not user: return
    msg = {
        "room": data['room'],
        "sender_id": str(user['_id']),
        "sender_name": user['display_name'],
        "sender_avatar": user['avatar'],
        "text": data.get('text', ''),
        "type": data.get('type', 'text'),
        "file_url": data.get('file_url', ''),
        "ts": datetime.datetime.utcnow().isoformat()
    }
    res = db.messages.insert_one(msg)
    msg['_id'] = str(res.inserted_id)
    emit('new_message', msg, room=data['room'])
    emit('notify', {"room": data['room']}, room=data['room'], include_self=False)

@socketio.on('delete_msg')
def handle_delete(data):
    db.messages.delete_one({"_id": ObjectId(data['msg_id'])})
    emit('msg_deleted', data['msg_id'], room=data['room'])

# WebRTC (Звонки)
@socketio.on('call_user')
def call(data): emit('incoming_call', data, room=data['room'], include_self=False)
@socketio.on('answer_call')
def answer(data): emit('call_accepted', data, room=data['room'])
@socketio.on('ice_candidate')
def ice(data): emit('ice_candidate', data['candidate'], room=data['room'], include_self=False)
@socketio.on('hangup')
def hangup(data): emit('call_ended', room=data['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
