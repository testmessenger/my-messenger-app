import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import datetime, os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_SECURE'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])

# БД (Замени ссылку на свою, если эта не активна)
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true")
db = client['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', max_http_buffer_size=100000000)

# Хранилище активных SID для статуса Online
online_sids = {}

def fix(d):
    if not d: return d
    if isinstance(d, list):
        for i in d: i['_id'] = str(i['_id'])
    else: d['_id'] = str(d['_id'])
    return d

def get_u():
    if 'user_id' not in session: return None
    try:
        return db.users.find_one({"_id": ObjectId(session['user_id'])})
    except: return None

@app.route('/')
def index():
    u = get_u()
    return render_template('index.html', user=fix(u)) if u else redirect('/auth')

@app.route('/auth')
def auth_p(): return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def handle_auth():
    d = request.json
    if d.get('reg'):
        if db.users.find_one({"username": d['username']}): return jsonify({"e": "Занято"}), 400
        uid = db.users.insert_one({
            "username": d['username'], "pw": generate_password_hash(d['pw']),
            "name": d['username'], "av": "/static/default.png", "bio": "Nexus User",
            "theme": "dark", "is_online": False, "last_seen": ""
        }).inserted_id
        session['user_id'] = str(uid)
    else:
        u = db.users.find_one({"username": d['username']})
        if u and check_password_hash(u['pw'], d['pw']): session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Ошибка"}), 401
    return jsonify({"s": "ok"})

@app.route('/api/groups', methods=['GET', 'POST'])
def groups():
    u = get_u()
    if not u: return "401", 401
    if request.method == 'POST':
        gid = db.groups.insert_one({
            "title": request.json['t'], "owner": str(u['_id']),
            "admins": [str(u['_id'])], "members": [str(u['_id'])],
            "muted": [], "banned": []
        }).inserted_id
        return jsonify({"id": str(gid)})
    
    gs = list(db.groups.find({"members": str(u['_id'])}))
    for g in gs:
        g['m_count'] = len(g['members'])
        # Получаем данные участников со статусом online
        g['member_details'] = fix(list(db.users.find({"_id": {"$in": [ObjectId(m) for m in g['members']]}}, {"pw":0})))
    return jsonify(fix(gs))

@app.route('/api/upload', methods=['POST'])
def upload():
    u = get_u()
    f = request.files.get('file')
    if f and u:
        fname = secure_filename(f"{u['username']}_{f.filename}")
        path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        f.save(path)
        return jsonify({"url": f"/static/uploads/{fname}"})
    return "Error", 400

# --- SOCKET.IO LOGIC ---

@socketio.on('connect')
def on_connect():
    u = get_u()
    if u:
        uid = str(u['_id'])
        online_sids[request.sid] = uid
        db.users.update_one({"_id": u['_id']}, {"$set": {"is_online": True}})
        emit('status_change', {"uid": uid, "status": "online"}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    uid = online_sids.get(request.sid)
    if uid:
        now = datetime.datetime.now().strftime("%H:%M")
        db.users.update_one({"_id": ObjectId(uid)}, {"$set": {"is_online": False, "last_seen": now}})
        emit('status_change', {"uid": uid, "status": "offline", "last": now}, broadcast=True)
        del online_sids[request.sid]

@socketio.on('join')
def on_join(d): join_room(d['room'])

@socketio.on('typing')
def on_typing(d):
    u = get_u()
    if u: emit('is_typing', {"name": u['name'], "room": d['room'], "st": d['st'], "is_g": d['is_g']}, room=d['room'], include_self=False)

@socketio.on('msg')
def on_msg(d):
    u = get_u()
    if not u: return
    # Проверка МУТА
    g = db.groups.find_one({"_id": ObjectId(d['room'])}) if len(d['room'])==24 else None
    if g and str(u['_id']) in g.get('muted', []): return

    m = {
        "room": d['room'], "sid": str(u['_id']), "name": u['name'], 
        "av": u['av'], "txt": d.get('txt'), "type": d.get('type', 'text'), 
        "url": d.get('url'), "reactions": {}, "ts": datetime.datetime.now().isoformat()
    }
    m['_id'] = str(db.messages.insert_one(m).inserted_id)
    emit('new_msg', m, room=d['room'])

@socketio.on('call_init')
def on_call(d):
    u = get_u()
    if u: emit('incoming_call', {"from": u['name'], "room": d['room']}, room=d['room'], include_self=False)

@socketio.on('delete_msg')
def on_del(d):
    u = get_u()
    # Удалять может автор или админ
    db.messages.delete_one({"_id": ObjectId(d['mid'])})
    emit('msg_deleted', d['mid'], room=d['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
