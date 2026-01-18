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
app.config['SECRET_KEY'] = 'nexus_infinity_2026'

# Подключение к БД
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

@app.route('/api/register', methods=['POST'])
def register():
    u, p = request.form.get('username'), request.form.get('password')
    if db.users.find_one({"username": u}): return "Занят", 400
    uid = db.users.insert_one({
        "username": u, "display_name": u,
        "password": generate_password_hash(p),
        "avatar": f"https://ui-avatars.com/api/?name={u}",
        "bio": "Nexus User"
    }).inserted_id
    session['user_id'] = str(uid)
    return redirect(url_for('index'))

@app.route('/api/my_chats')
def get_my_chats():
    user = get_user()
    if not user: return jsonify([])
    groups = list(db.groups.find({"members": str(user['_id'])}))
    for g in groups: g['_id'] = str(g['_id'])
    return jsonify(groups)

@app.route('/api/groups/create', methods=['POST'])
def create_group():
    user = get_user()
    gid = db.groups.insert_one({
        "title": request.json['title'],
        "owner_id": str(user['_id']),
        "members": [str(user['_id'])],
        "admins": [str(user['_id'])],
        "muted": []
    }).inserted_id
    return jsonify({"id": str(gid)})

@app.route('/api/group/manage', methods=['POST'])
def manage_member():
    user = get_user()
    data = request.json
    group = db.groups.find_one({"_id": ObjectId(data['room_id'])})
    if str(user['_id']) != group['owner_id'] and str(user['_id']) not in group['admins']:
        return "No power", 403
    
    if data['action'] == 'make_admin':
        db.groups.update_one({"_id": group['_id']}, {"$addToSet": {"admins": data['target_id']}})
    elif data['action'] == 'kick':
        db.groups.update_one({"_id": group['_id']}, {"$pull": {"members": data['target_id'], "admins": data['target_id']}})
    return jsonify({"status": "ok"})

@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    u = db.users.find_one({"_id": ObjectId(user_id)}, {"password": 0})
    if u: u['_id'] = str(u['_id'])
    return jsonify(u)

@app.route('/api/upload', methods=['POST'])
def upload():
    file = request.files['file']
    encoded = base64.b64encode(file.read()).decode('utf-8')
    return jsonify({"url": f"data:{file.content_type};base64,{encoded}"})

@app.route('/api/profile/save', methods=['POST'])
def save_profile():
    user = get_user()
    data = request.json
    upd = {"display_name": data['name'], "bio": data['bio']}
    if data.get('avatar'): upd["avatar"] = data.get('avatar')
    db.users.update_one({"_id": user['_id']}, {"$set": upd})
    return jsonify({"status": "ok"})

@app.route('/api/room/<room_id>/members')
def get_members(room_id):
    if room_id == 'general':
        users = list(db.users.find({}, {"password":0}))
    elif "_" in room_id:
        ids = [ObjectId(x) for x in room_id.split("_")]
        users = list(db.users.find({"_id": {"$in": ids}}, {"password":0}))
    else:
        group = db.groups.find_one({"_id": ObjectId(room_id)})
        users = list(db.users.find({"_id": {"$in": [ObjectId(m) for m in group['members']]}}, {"password":0}))
    for u in users: u['_id'] = str(u['_id'])
    return jsonify(users)

# --- SOCKET.IO (СИГНАЛИНГ И СООБЩЕНИЯ) ---
@socketio.on('join_room')
def handle_join(data):
    join_room(data['room'])
    msgs = list(db.messages.find({"room": data['room']}).sort("ts", -1).limit(40))
    for m in reversed(msgs):
        m['_id'] = str(m['_id'])
        emit('new_message', m)

@socketio.on('send_msg')
def handle_msg(data):
    user = get_user()
    msg = {
        "room": data['room'], "sender_id": str(user['_id']),
        "sender_name": user['display_name'], "sender_avatar": user['avatar'],
        "text": data.get('text', ''), "type": data.get('type', 'text'),
        "file_url": data.get('file_url', ''), "ts": datetime.datetime.utcnow().isoformat(),
        "reactions": {}
    }
    res = db.messages.insert_one(msg)
    msg['_id'] = str(res.inserted_id)
    emit('new_message', msg, room=data['room'])
    emit('notify', {"title": user['display_name'], "body": data.get('text', 'Файл')}, room=data['room'], include_self=False)

@socketio.on('add_reaction')
def handle_react(data):
    db.messages.update_one({"_id": ObjectId(data['msg_id'])}, {"$set": {f"reactions.{data['emoji']}": True}})
    emit('reaction_update', data, room=data['room'])

@socketio.on('call_user')
def call(data):
    emit('incoming_call', data, room=data['room'], include_self=False)

@socketio.on('answer_call')
def answer(data):
    emit('call_accepted', data, room=data['room'])

@socketio.on('ice_candidate')
def ice(data):
    emit('ice_candidate', data['candidate'], room=data['room'], include_self=False)

@socketio.on('hangup')
def hangup(data):
    emit('call_ended', room=data['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
