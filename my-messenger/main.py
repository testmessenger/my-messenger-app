import eventlet
eventlet.monkey_patch()

import os
import datetime
import base64
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nexus_core_2026_pro'

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

# --- API: ПОИСК И ГРУППЫ ---
@app.route('/api/search', methods=['GET'])
def search():
    q = request.args.get('q', '')
    users = list(db.users.find({"username": {"$regex": q, "$options": "i"}}, {"password": 0}).limit(10))
    groups = list(db.groups.find({"title": {"$regex": q, "$options": "i"}}).limit(10))
    for x in users + groups: x['_id'] = str(x['_id'])
    return jsonify({"users": users, "groups": groups})

@app.route('/api/groups/create', methods=['POST'])
def create_group():
    user = get_user()
    data = request.json
    gid = db.groups.insert_one({
        "title": data['title'],
        "owner_id": str(user['_id']),
        "admins": [str(user['_id'])],
        "members": [str(user['_id'])],
        "type": "group"
    }).inserted_id
    return jsonify({"id": str(gid)})

@app.route('/api/upload', methods=['POST'])
def upload():
    file = request.files['file']
    encoded = base64.b64encode(file.read()).decode('utf-8')
    return jsonify({"url": f"data:{file.content_type};base64,{encoded}"})

# --- SOCKET.IO ---
@socketio.on('join_room')
def on_join(data):
    room = data['room']
    join_room(room)
    msgs = list(db.messages.find({"room": room}).sort("ts", -1).limit(50))
    for m in reversed(msgs):
        m['_id'] = str(m['_id'])
        emit('new_message', m)

@socketio.on('send_msg')
def handle_msg(data):
    user = get_user()
    room = data.get('room')
    
    # Проверка на бан/мут в группах
    group = db.groups.find_one({"_id": ObjectId(room)}) if len(room) == 24 else None
    if group and str(user['_id']) in group.get('banned', []): return

    msg_obj = {
        "room": room,
        "sender_id": str(user['_id']),
        "sender_name": user['display_name'],
        "sender_avatar": user['avatar'],
        "text": data.get('text', ''),
        "type": data.get('type', 'text'),
        "file_url": data.get('file_url', ''),
        "reactions": {},
        "ts": datetime.datetime.utcnow().isoformat()
    }
    res = db.messages.insert_one(msg_obj)
    msg_obj['_id'] = str(res.inserted_id)
    emit('new_message', msg_obj, room=room)

@socketio.on('delete_msg')
def delete(data):
    user = get_user()
    msg = db.messages.find_one({"_id": ObjectId(data['msg_id'])})
    if not msg: return
    
    can_delete = False
    if str(msg['sender_id']) == str(user['_id']):
        can_delete = True # Своё удалять можно всем
    else:
        # Проверка на админа в группе
        if len(msg['room']) == 24:
            group = db.groups.find_one({"_id": ObjectId(msg['room'])})
            if group and str(user['_id']) in group.get('admins', []):
                can_delete = True

    if can_delete:
        db.messages.delete_one({"_id": ObjectId(data['msg_id'])})
        emit('msg_deleted', data['msg_id'], room=msg['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
