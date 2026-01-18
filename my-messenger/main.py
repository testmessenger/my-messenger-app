import eventlet
eventlet.monkey_patch()
import datetime, base64, os
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nexus_ultra_full_2026'

# Подключение к БД
MONGO_URI = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
db = MongoClient(MONGO_URI)['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=10000000)

def get_user():
    return db.users.find_one({"_id": ObjectId(session['user_id'])}) if 'user_id' in session else None

# --- АВТОРИЗАЦИЯ ---
@app.route('/api/auth/register', methods=['POST'])
def register():
    d = request.json
    if db.users.find_one({"username": d['username']}): return jsonify({"error": "Ник занят"}), 400
    uid = db.users.insert_one({
        "username": d['username'], "password": generate_password_hash(d['password']),
        "display_name": d['username'], "avatar": "https://cdn-icons-png.flaticon.com/512/149/149071.png",
        "bio": "New user", "theme": "dark"
    }).inserted_id
    session['user_id'] = str(uid)
    return jsonify({"status": "ok"})

@app.route('/api/auth/login', methods=['POST'])
def login():
    d = request.json
    u = db.users.find_one({"username": d['username']})
    if u and check_password_hash(u['password'], d['password']):
        session['user_id'] = str(u['_id'])
        return jsonify({"status": "ok"})
    return jsonify({"error": "Ошибка входа"}), 401

# --- ГРУППЫ И АДМИНКА ---
@app.route('/api/groups/create', methods=['POST'])
def create_group():
    u = get_user()
    gid = db.groups.insert_one({
        "title": request.json['title'], "owner_id": str(u['_id']),
        "admins": [str(u['_id'])], "members": [str(u['_id'])],
        "banned": [], "muted": []
    }).inserted_id
    return jsonify({"id": str(gid)})

@app.route('/api/admin/action', methods=['POST'])
def admin_action():
    u = get_user()
    d = request.json # {gid, target_id, type: 'ban'|'mute'|'unmute'|'promote'}
    g = db.groups.find_one({"_id": ObjectId(d['gid'])})
    if str(u['_id']) not in g['admins']: return "No rights", 403
    
    if d['type'] == 'ban':
        db.groups.update_one({"_id": g['_id']}, {"$pull": {"members": d['target_id']}, "$push": {"banned": d['target_id']}})
    elif d['type'] == 'mute':
        db.groups.update_one({"_id": g['_id']}, {"$push": {"muted": d['target_id']}})
    elif d['type'] == 'promote' and g['owner_id'] == str(u['_id']):
        db.groups.update_one({"_id": g['_id']}, {"$push": {"admins": d['target_id']}})
    return jsonify({"status": "ok"})

# --- СООБЩЕНИЯ И ИСТОРИЯ ---
@app.route('/api/history/<rid>')
def history(rid):
    msgs = list(db.messages.find({"room": rid}).sort("ts", -1).limit(50))
    for m in msgs: m['_id'] = str(m['_id'])
    return jsonify(msgs[::-1])

@app.route('/')
def index():
    u = get_user()
    return render_template('index.html', user=u) if u else redirect('/auth')

@app.route('/auth')
def auth_page(): return render_template('auth.html')

# --- SOCKETS (ЗВОНКИ, РЕАКЦИИ, УДАЛЕНИЕ) ---
@socketio.on('join_room')
def on_join(d):
    u = get_user()
    if len(d['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if g and str(u['_id']) in g['banned']: return
    join_room(d['room'])

@socketio.on('send_msg')
def handle_msg(d):
    u = get_user()
    if len(d['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if str(u['_id']) in g.get('muted', []): return

    msg = {
        "room": d['room'], "sender_id": str(u['_id']), "sender_name": u['display_name'],
        "avatar": u['avatar'], "text": d.get('text'), "type": d.get('type', 'text'),
        "file_url": d.get('file_url'), "reactions": {}, "ts": datetime.datetime.utcnow().isoformat()
    }
    msg['_id'] = str(db.messages.insert_one(msg).inserted_id)
    emit('new_message', msg, room=d['room'])

@socketio.on('delete_msg')
def del_msg(d):
    u = get_user()
    m = db.messages.find_one({"_id": ObjectId(d['mid'])})
    g = db.groups.find_one({"_id": ObjectId(m['room'])}) if len(m['room'])==24 else None
    if m['sender_id'] == str(u['_id']) or (g and str(u['_id']) in g['admins']):
        db.messages.delete_one({"_id": ObjectId(d['mid'])})
        emit('msg_deleted', d['mid'], room=m['room'])

@socketio.on('add_reaction')
def add_reaction(d):
    db.messages.update_one({"_id": ObjectId(d['mid'])}, {"$inc": {f"reactions.{d['emoji']}": 1}})
    emit('update_reactions', d, room=d['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
