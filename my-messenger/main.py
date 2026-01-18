import eventlet
eventlet.monkey_patch()

import os
import datetime
import base64
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nexus_ultra_call_system_2026'

MONGO_URI = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URI)
db = client['messenger_db']

socketio = SocketIO(app, cors_allowed_origins="*")

def get_user():
    if 'user_id' in session:
        return db.users.find_one({"_id": ObjectId(session['user_id'])})
    return None

@app.route('/')
def index():
    user = get_user()
    if not user: return redirect(url_for('auth'))
    return render_template('index.html', user=user)

@app.route('/auth')
def auth(): return render_template('auth.html')

# --- API (БЕЗ ВЫРЕЗАНИЯ) ---
@app.route('/api/my_chats')
def get_my_chats():
    user = get_user()
    groups = list(db.groups.find({"members": str(user['_id'])}))
    for g in groups: g['_id'] = str(g['_id'])
    return jsonify(groups)

@app.route('/api/upload', methods=['POST'])
def upload():
    file = request.files['file']
    encoded = base64.b64encode(file.read()).decode('utf-8')
    return jsonify({"url": f"data:{file.content_type};base64,{encoded}"})

@app.route('/api/room/<room_id>/members')
def get_members(room_id):
    if room_id == 'general':
        users = list(db.users.find({}, {"password":0}).limit(50))
    elif "_" in room_id:
        ids = [ObjectId(x) for x in room_id.split("_")]
        users = list(db.users.find({"_id": {"$in": ids}}, {"password":0}))
    else:
        group = db.groups.find_one({"_id": ObjectId(room_id)})
        users = list(db.users.find({"_id": {"$in": [ObjectId(m) for m in group['members']]}}, {"password":0}))
    for u in users: u['_id'] = str(u['_id'])
    return jsonify(users)

# --- SOCKET.IO (ЗВОНКИ И УВЕДОМЛЕНИЯ) ---
@socketio.on('join_room')
def on_join(data):
    join_room(data['room'])

@socketio.on('send_msg')
def handle_msg(data):
    user = get_user()
    msg = {
        "room": data['room'], "sender_id": str(user['_id']),
        "sender_name": user['display_name'], "sender_avatar": user['avatar'],
        "text": data.get('text', ''), "type": data.get('type', 'text'),
        "file_url": data.get('file_url', ''), "ts": datetime.datetime.utcnow().isoformat()
    }
    db.messages.insert_one(msg)
    emit('new_message', msg, room=data['room'])
    # Уведомление для других
    emit('notify', {"title": f"Новое от {user['display_name']}", "body": data.get('text', 'Файл/Кружок')}, room=data['room'], include_self=False)

# WebRTC Сигналинг
@socketio.on('call_user')
def call_user(data):
    emit('incoming_call', {
        "from": data['from'],
        "caller_name": data['caller_name'],
        "room": data['room'],
        "offer": data['offer']
    }, room=data['room'], include_self=False)

@socketio.on('answer_call')
def answer_call(data):
    emit('call_accepted', {"answer": data['answer']}, room=data['room'])

@socketio.on('ice_candidate')
def ice_candidate(data):
    emit('ice_candidate', data['candidate'], room=data['room'], include_self=False)

@socketio.on('hangup')
def hangup(data):
    emit('call_ended', room=data['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
