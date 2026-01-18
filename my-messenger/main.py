import eventlet
eventlet.monkey_patch()
import datetime, base64
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nexus_god_mode_2026'

# БД
MONGO_URI = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
db = MongoClient(MONGO_URI)['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*")

def get_user():
    return db.users.find_one({"_id": ObjectId(session['user_id'])}) if 'user_id' in session else None

@app.route('/')
def index():
    u = get_user()
    return render_template('index.html', user=u) if u else redirect(url_for('auth'))

@app.route('/auth')
def auth(): return render_template('auth.html')

# --- СИСТЕМА АВТОРИЗАЦИИ ---
@app.route('/api/auth/<action>', methods=['POST'])
def auth_api(action):
    d = request.json
    if action == 'register':
        if db.users.find_one({"username": d['username']}): return jsonify({"error": "Ник занят"}), 400
        uid = db.users.insert_one({"username": d['username'], "password": generate_password_hash(d['password']), "display_name": d['username'], "avatar": "https://cdn-icons-png.flaticon.com/512/149/149071.png", "bio": "Nexus User", "theme": "dark"}).inserted_id
        session['user_id'] = str(uid)
    else:
        u = db.users.find_one({"username": d['username']})
        if u and check_password_hash(u['password'], d['password']): session['user_id'] = str(u['_id'])
        else: return jsonify({"error": "Ошибка"}), 401
    return jsonify({"status": "ok"})

# --- ГРУППЫ И АДМИНКА ---
@app.route('/api/groups/create', methods=['POST'])
def create_grp():
    u = get_user()
    gid = db.groups.insert_one({"title": request.json['title'], "owner_id": str(u['_id']), "admins": [str(u['_id'])], "members": [str(u['_id'])], "banned": [], "muted": []}).inserted_id
    return jsonify({"id": str(gid)})

@app.route('/api/groups/action', methods=['POST'])
def grp_action():
    u = get_user()
    d = request.json # {gid, target_id, action: 'ban'|'mute'|'promote'}
    g = db.groups.find_one({"_id": ObjectId(d['gid'])})
    if str(u['_id']) not in g['admins']: return "No rights", 403
    
    if d['action'] == 'ban':
        db.groups.update_one({"_id": g['_id']}, {"$pull": {"members": d['target_id']}, "$push": {"banned": d['target_id']}})
    elif d['action'] == 'mute':
        db.groups.update_one({"_id": g['_id']}, {"$push": {"muted": d['target_id']}})
    elif d['action'] == 'promote' and g['owner_id'] == str(u['_id']):
        db.groups.update_one({"_id": g['_id']}, {"$push": {"admins": d['target_id']}})
    return jsonify({"status": "ok"})

# --- ИСТОРИЯ И ПРОФИЛИ ---
@app.route('/api/chat/history/<rid>')
def get_history(rid):
    msgs = list(db.messages.find({"room": rid}).sort("ts", -1).limit(50))
    for m in msgs: m['_id'] = str(m['_id'])
    return jsonify(msgs[::-1])

@app.route('/api/user/<uid>')
def get_user_info(uid):
    u = db.users.find_one({"_id": ObjectId(uid)}, {"password": 0})
    u['_id'] = str(u['_id'])
    return jsonify(u)

@app.route('/api/profile/update', methods=['POST'])
def up_prof():
    u = get_user()
    db.users.update_one({"_id": u['_id']}, {"$set": request.json})
    return "ok"

# --- SOCKETS ---
@socketio.on('join_room')
def on_j(d):
    u = get_user()
    g = db.groups.find_one({"_id": ObjectId(d['room'])}) if len(d['room'])==24 else None
    if g and str(u['_id']) in g['banned']: return
    join_room(d['room'])

@socketio.on('send_msg')
def handle_m(d):
    u = get_user()
    if not u: return
    # Проверка мута
    if len(d['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if str(u['_id']) in g.get('muted', []): return
        
    msg = {"room": d['room'], "sender_id": str(u['_id']), "sender_name": u['display_name'], "avatar": u['avatar'], "text": d.get('text'), "type": d.get('type', 'text'), "file_url": d.get('file_url'), "reactions": {}, "ts": datetime.datetime.utcnow().isoformat()}
    msg['_id'] = str(db.messages.insert_one(msg).inserted_id)
    emit('new_message', msg, room=d['room'])

@socketio.on('delete_msg')
def del_m(d):
    u = get_user()
    m = db.messages.find_one({"_id": ObjectId(d['mid'])})
    g = db.groups.find_one({"_id": ObjectId(m['room'])}) if len(m['room'])==24 else None
    is_admin = g and str(u['_id']) in g['admins']
    if m['sender_id'] == str(u['_id']) or is_admin:
        db.messages.delete_one({"_id": ObjectId(d['mid'])})
        emit('msg_deleted', d['mid'], room=m['room'])

@socketio.on('add_reaction')
def react(d):
    db.messages.update_one({"_id": ObjectId(d['mid'])}, {"$inc": {f"reactions.{d['emoji']}": 1}})
    emit('update_reactions', d, room=d['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
