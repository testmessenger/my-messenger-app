import eventlet
eventlet.monkey_patch()
import datetime, os
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_CORE_ULTRA_2026'

# БД (adminbase:admin123 - твои данные)
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true")
db = client['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50000000)

def get_u():
    u = db.users.find_one({"_id": ObjectId(session['user_id'])}) if 'user_id' in session else None
    if u: db.users.update_one({"_id": u['_id']}, {"$set": {"last_seen": datetime.datetime.utcnow()}})
    return u

@app.route('/')
def index(): return render_template('index.html', user=get_u()) if 'user_id' in session else redirect('/auth')

@app.route('/auth')
def auth_pg(): return render_template('auth.html')

# --- АВТОРИЗАЦИЯ И ПРОФИЛЬ ---
@app.route('/api/auth', methods=['POST'])
def handle_auth():
    d = request.json
    if d.get('reg'):
        if db.users.find_one({"username": d['username']}): return jsonify({"e": "Ник занят"}), 400
        uid = db.users.insert_one({"username": d['username'], "pw": generate_password_hash(d['pw']), "name": d['username'], "av": "https://ui-avatars.com/api/?name="+d['username'], "bio": "Nexus User", "theme": "dark", "last_seen": datetime.datetime.utcnow()}).inserted_id
        session['user_id'] = str(uid)
    else:
        u = db.users.find_one({"username": d['username']})
        if u and check_password_hash(u['pw'], d['pw']): session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Ошибка входа"}), 401
    return jsonify({"s": "ok"})

@app.route('/api/user/update', methods=['POST'])
def update_user():
    db.users.update_one({"_id": get_u()['_id']}, {"$set": request.json})
    return "ok"

# --- ГРУППЫ И АДМИНИСТРИРОВАНИЕ ---
@app.route('/api/groups', methods=['GET', 'POST'])
def groups():
    u = get_u()
    if request.method == 'POST':
        gid = db.groups.insert_one({
            "title": request.json['t'], "owner": str(u['_id']), "admins": [str(u['_id'])],
            "members": [str(u['_id'])], "banned": [], "muted": []
        }).inserted_id
        return jsonify({"id": str(gid)})
    return jsonify(list(db.groups.find({"members": str(u['_id'])})))

@app.route('/api/admin_action', methods=['POST'])
def admin_action():
    u = get_u()
    d = request.json # gid, target_id, action (ban, mute, promote)
    g = db.groups.find_one({"_id": ObjectId(d['gid'])})
    if str(u['_id']) not in g['admins']: return "No rights", 403
    
    if d['action'] == 'ban':
        db.groups.update_one({"_id": g['_id']}, {"$pull": {"members": d['target_id']}, "$push": {"banned": d['target_id']}})
    elif d['action'] == 'mute':
        db.groups.update_one({"_id": g['_id']}, {"$push": {"muted": d['target_id']}})
    elif d['action'] == 'promote' and g['owner'] == str(u['_id']):
        db.groups.update_one({"_id": g['_id']}, {"$push": {"admins": d['target_id']}})
    return "ok"

# --- СООБЩЕНИЯ И ИСТОРИЯ ---
@app.route('/api/history/<rid>')
def get_history(rid):
    ms = list(db.messages.find({"room": rid}).sort("ts", -1).limit(50))
    for m in ms: m['_id'] = str(m['_id'])
    return jsonify(ms[::-1])

# --- SOCKETS: РЕАЛЬНОЕ ВРЕМЯ ---
@socketio.on('join')
def on_join(d): join_room(d['room'])

@socketio.on('typing')
def on_typing(d):
    u = get_u()
    emit('display_typing', {"name": u['name'], "room": d['room'], "st": d['st'], "is_g": d['is_g']}, room=d['room'], include_self=False)

@socketio.on('msg')
def handle_msg(d):
    u = get_u()
    # Проверка мута
    if len(d['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if str(u['_id']) in g.get('muted', []):
            emit('error_msg', 'Вы в муте!', room=request.sid)
            return

    msg = {
        "room": d['room'], "sid": str(u['_id']), "name": u['name'], "av": u['av'],
        "txt": d.get('txt'), "type": d.get('type', 'text'), "url": d.get('url'),
        "reacts": {}, "ts": datetime.datetime.utcnow().isoformat()
    }
    msg['_id'] = str(db.messages.insert_one(msg).inserted_id)
    emit('new_msg', msg, room=d['room'])

@socketio.on('call_start')
def call_user(d):
    u = get_u()
    emit('incoming_call', {"from": u['name'], "from_id": str(u['_id']), "room": d['room']}, room=d['room'], include_self=False)

@socketio.on('del_msg')
def delete_msg(d):
    u = get_u()
    m = db.messages.find_one({"_id": ObjectId(d['mid'])})
    g = db.groups.find_one({"_id": ObjectId(m['room'])}) if len(m['room']) == 24 else None
    if m['sid'] == str(u['_id']) or (g and str(u['_id']) in g['admins']):
        db.messages.delete_one({"_id": ObjectId(d['mid'])})
        emit('msg_deleted', d['mid'], room=m['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
