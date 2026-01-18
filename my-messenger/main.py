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
app.config['SECRET_KEY'] = 'nexus_elite_2026'

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

# --- API: ГРУППЫ И СПИСОК ЧАТОВ ---
@app.route('/api/my_chats')
def get_my_chats():
    user = get_user()
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
        "muted": [], "banned": []
    }).inserted_id
    return jsonify({"id": str(gid)})

# --- API: УПРАВЛЕНИЕ УЧАСТНИКАМИ ---
@app.route('/api/group/manage', methods=['POST'])
def manage_member():
    user = get_user()
    data = request.json # {room_id, target_id, action}
    group = db.groups.find_one({"_id": ObjectId(data['room_id'])})
    
    if str(user['_id']) != group['owner_id'] and str(user['_id']) not in group['admins']:
        return "No power", 403

    if data['action'] == 'make_admin':
        db.groups.update_one({"_id": group['_id']}, {"$addToSet": {"admins": data['target_id']}})
    elif data['action'] == 'kick':
        db.groups.update_one({"_id": group['_id']}, {"$pull": {"members": data['target_id'], "admins": data['target_id']}})
    elif data['action'] == 'mute':
        db.groups.update_one({"_id": group['_id']}, {"$addToSet": {"muted": data['target_id']}})
    
    return jsonify({"status": "ok"})

# --- API: ПРОФИЛЬ И ЗАГРУЗКА ---
@app.route('/api/profile/save', methods=['POST'])
def save_profile():
    user = get_user()
    data = request.json
    upd = {"display_name": data['name'], "bio": data['bio']}
    if data.get('avatar'): upd["avatar"] = data.get('avatar')
    db.users.update_one({"_id": user['_id']}, {"$set": upd})
    return jsonify({"status": "ok"})

@app.route('/api/upload', methods=['POST'])
def upload():
    file = request.files['file']
    encoded = base64.b64encode(file.read()).decode('utf-8')
    return jsonify({"url": f"data:{file.content_type};base64,{encoded}"})

@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    u = db.users.find_one({"_id": ObjectId(user_id)}, {"password": 0})
    u['_id'] = str(u['_id'])
    return jsonify(u)

# --- SOCKET.IO ---
@socketio.on('join_room')
def on_join(data):
    join_room(data['room'])
    msgs = list(db.messages.find({"room": data['room']}).sort("ts", -1).limit(40))
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
        "file_url": data.get('file_url', ''), "ts": datetime.datetime.utcnow().isoformat(),
        "reactions": {}
    }
    res = db.messages.insert_one(msg_obj)
    msg_obj['_id'] = str(res.inserted_id)
    emit('new_message', msg_obj, room=data['room'])

@socketio.on('add_reaction')
def react(data):
    db.messages.update_one({"_id": ObjectId(data['msg_id'])}, {"$set": {f"reactions.{data['emoji']}": True}})
    emit('reaction_update', data, room=data['room'])

@socketio.on('delete_msg')
def delete(data):
    db.messages.delete_one({"_id": ObjectId(data['msg_id'])})
    emit('msg_deleted', data['msg_id'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
