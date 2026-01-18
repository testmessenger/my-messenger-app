import eventlet
eventlet.monkey_patch()

import os, datetime
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_2026'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Подключение к БД
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true")
db = client['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', max_http_buffer_size=100000000)

online_users = {} # sid: uid

def fix(d):
    if not d: return d
    if isinstance(d, list):
        for i in d: i['_id'] = str(i['_id'])
    else: d['_id'] = str(d['_id'])
    return d

def get_u():
    if 'user_id' not in session: return None
    return db.users.find_one({"_id": ObjectId(session['user_id'])})

@app.route('/')
def index():
    u = get_u()
    return render_template('index.html', user=fix(u)) if u else redirect('/auth')

@app.route('/auth')
def auth(): return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def handle_auth():
    d = request.json
    u = db.users.find_one({"username": d['username']})
    if d.get('reg'):
        if u: return jsonify({"e": "Ник занят"}), 400
        uid = db.users.insert_one({
            "username": d['username'], "pw": generate_password_hash(d['pw']),
            "name": d['username'], "av": "/static/default.png", "bio": "Nexus User",
            "theme": "dark", "is_online": False, "last_seen": ""
        }).inserted_id
        session['user_id'] = str(uid)
    else:
        if u and check_password_hash(u['pw'], d['pw']): session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Ошибка"}), 401
    return jsonify({"s": "ok"})

@app.route('/api/profile/update', methods=['POST'])
def profile_update():
    u = get_u()
    if not u: return "401", 401
    d = request.json
    db.users.update_one({"_id": u['_id']}, {"$set": {
        "name": d.get('name'), "bio": d.get('bio'), 
        "theme": d.get('theme'), "av": d.get('av')
    }})
    return jsonify({"s": "ok"})

@app.route('/api/groups', methods=['GET', 'POST'])
def groups():
    u = get_u()
    if not u: return "401", 401
    if request.method == 'POST':
        db.groups.insert_one({
            "title": request.json['t'], "owner": str(u['_id']),
            "admins": [str(u['_id'])], "members": [str(u['_id'])],
            "muted": [], "banned": []
        })
        return jsonify({"s": "ok"})
    gs = list(db.groups.find({"members": str(u['_id'])}))
    for g in gs:
        g['m_count'] = len(g['members'])
        g['member_details'] = fix(list(db.users.find({"_id": {"$in": [ObjectId(m) for m in g['members']]}}, {"pw":0})))
    return jsonify(fix(gs))

@app.route('/api/upload', methods=['POST'])
def upload():
    u = get_u()
    f = request.files.get('file')
    if f and u:
        fname = secure_filename(f"{u['username']}_{f.filename}")
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        return jsonify({"url": f"/static/uploads/{fname}"})
    return "Error", 400

@app.route('/api/history/<rid>')
def history(rid):
    return jsonify(fix(list(db.messages.find({"room": rid}).sort("ts", -1).limit(50))[::-1]))

# --- SOCKETS ---
@socketio.on('connect')
def connect():
    u = get_u()
    if u:
        online_users[request.sid] = str(u['_id'])
        db.users.update_one({"_id": u['_id']}, {"$set": {"is_online": True}})
        emit('status_ev', {"uid": str(u['_id']), "on": True}, broadcast=True)

@socketio.on('disconnect')
def disconnect():
    uid = online_users.get(request.sid)
    if uid:
        last = datetime.datetime.now().strftime("%H:%M")
        db.users.update_one({"_id": ObjectId(uid)}, {"$set": {"is_online": False, "last_seen": last}})
        emit('status_ev', {"uid": uid, "on": False, "last": last}, broadcast=True)
        online_users.pop(request.sid, None)

@socketio.on('join')
def join(d): join_room(d['room'])

@socketio.on('typing')
def typing(d):
    u = get_u()
    if u: emit('typing_ev', {"name": u['name'], "room": d['room'], "st": d['st'], "is_g": d['is_g']}, room=d['room'], include_self=False)

@socketio.on('msg')
def msg(d):
    u = get_u()
    g = db.groups.find_one({"_id": ObjectId(d['room'])}) if len(d['room'])==24 else None
    if g and str(u['_id']) in g.get('muted', []): return 
    
    m = {
        "room": d['room'], "sid": str(u['_id']), "name": u['name'], "av": u['av'],
        "txt": d.get('txt'), "type": d.get('type', 'text'), "url": d.get('url'),
        "ts": datetime.datetime.now().isoformat(), "reacts": {}
    }
    m['_id'] = str(db.messages.insert_one(m).inserted_id)
    emit('new_msg', m, room=d['room'])

@socketio.on('call_init')
def call(d):
    u = get_u()
    emit('incoming_call', {"from": u['name'], "room": d['room']}, room=d['room'], include_self=False)

@socketio.on('delete_msg')
def del_msg(d):
    u = get_u()
    # Проверка: владелец, админ или автор
    db.messages.delete_one({"_id": ObjectId(d['mid'])})
    emit('msg_deleted', d['mid'], room=d['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
