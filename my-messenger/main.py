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
app.config['SECRET_KEY'] = 'nexus_global_mobile_2026'

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

# --- API: ПРОФИЛЬ ---
@app.route('/api/profile/save', methods=['POST'])
def save_profile():
    user = get_user()
    if not user: return jsonify({"error": "401"}), 401
    data = request.json
    upd = {"display_name": data.get('name'), "bio": data.get('bio')}
    if data.get('avatar'): upd["avatar"] = data.get('avatar')
    db.users.update_one({"_id": user['_id']}, {"$set": upd})
    return jsonify({"status": "ok"})

@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    u = db.users.find_one({"_id": ObjectId(user_id)}, {"password": 0})
    if u: u['_id'] = str(u['_id']); return jsonify(u)
    return jsonify({"error": "404"}), 404

# --- API: ГРУППЫ (ИСПРАВЛЕНО) ---
@app.route('/api/groups/create', methods=['POST'])
def create_group():
    user = get_user()
    data = request.json
    new_group = {
        "title": data['title'],
        "owner_id": str(user['_id']),
        "members": [str(user['_id'])],
        "admins": [str(user['_id'])],
        "created_at": datetime.datetime.utcnow()
    }
    gid = db.groups.insert_one(new_group).inserted_id
    return jsonify({"id": str(gid), "title": data['title']})

@app.route('/api/room/<room_id>/members')
def get_members(room_id):
    if room_id == 'general':
        users = list(db.users.find({}, {"password": 0}).limit(50))
    else:
        if "_" in room_id:
            ids = [ObjectId(x) for x in room_id.split("_")]
            users = list(db.users.find({"_id": {"$in": ids}}, {"password": 0}))
        else:
            group = db.groups.find_one({"_id": ObjectId(room_id)})
            users = list(db.users.find({"_id": {"$in": [ObjectId(m) for m in group.get('members', [])]}}, {"password": 0}))
    for u in users: u['_id'] = str(u['_id'])
    return jsonify(users)

@app.route('/api/search')
def search():
    q = request.args.get('q', '')
    users = list(db.users.find({"username": {"$regex": q, "$options": "i"}}, {"password": 0}).limit(5))
    groups = list(db.groups.find({"title": {"$regex": q, "$options": "i"}}).limit(5))
    for x in users + groups: x['_id'] = str(x['_id'])
    return jsonify({"users": users, "groups": groups})

@app.route('/api/upload', methods=['POST'])
def upload():
    file = request.files['file']
    encoded = base64.b64encode(file.read()).decode('utf-8')
    return jsonify({"url": f"data:{file.content_type};base64,{encoded}"})

@app.route('/api/register', methods=['POST'])
def register():
    data = request.form
    if db.users.find_one({"username": data['username']}): return "Error", 400
    uid = db.users.insert_one({
        "username": data['username'], "display_name": data['username'],
        "password": generate_password_hash(data['password']),
        "avatar": f"https://ui-avatars.com/api/?name={data['username']}",
        "bio": "Nexus User"
    }).inserted_id
    session['user_id'] = str(uid)
    return redirect(url_for('index'))

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
    msg_obj = {
        "room": data['room'], "sender_id": str(user['_id']),
        "sender_name": user['display_name'], "sender_avatar": user['avatar'],
        "text": data.get('text', ''), "type": data.get('type', 'text'),
        "file_url": data.get('file_url', ''), "ts": datetime.datetime.utcnow().isoformat()
    }
    res = db.messages.insert_one(msg_obj)
    msg_obj['_id'] = str(res.inserted_id)
    emit('new_message', msg_obj, room=data['room'])

@socketio.on('delete_msg')
def delete(data):
    user = get_user()
    msg = db.messages.find_one({"_id": ObjectId(data['msg_id'])})
    if msg and str(msg['sender_id']) == str(user['_id']):
        db.messages.delete_one({"_id": ObjectId(data['msg_id'])})
        emit('msg_deleted', data['msg_id'], room=msg['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
