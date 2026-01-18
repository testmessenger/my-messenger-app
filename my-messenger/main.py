import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, session, redirect, jsonify, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_MEGA_2026'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# MongoDB
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true")
db = client['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100000000)

def fix(d):
    if not d: return d
    if isinstance(d, list):
        for i in d: i['_id'] = str(i['_id'])
    else: d['_id'] = str(d['_id'])
    return d

def get_u():
    if 'user_id' not in session: return None
    u = db.users.find_one({"_id": ObjectId(session['user_id'])})
    if u:
        db.users.update_one({"_id": u['_id']}, {"$set": {"last_seen": datetime.datetime.utcnow().isoformat()}})
    return u

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
        if db.users.find_one({"username": d['username']}): return jsonify({"e": "Username taken"}), 400
        uid = db.users.insert_one({
            "username": d['username'], "pw": generate_password_hash(d['pw']),
            "name": d['username'], "av": "/static/default_av.png",
            "bio": "Nexus User", "theme": "dark", "last_seen": ""
        }).inserted_id
        session['user_id'] = str(uid)
    else:
        u = db.users.find_one({"username": d['username']})
        if u and check_password_hash(u['pw'], d['pw']): session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Error"}), 401
    return jsonify({"s": "ok"})

@app.route('/api/upload', methods=['POST'])
def upload():
    u = get_u()
    file = request.files.get('file')
    if file:
        fname = secure_filename(f"{u['_id']}_{file.filename}")
        path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        file.save(path)
        url = f"/static/uploads/{fname}"
        if request.form.get('type') == 'avatar':
            db.users.update_one({"_id": u['_id']}, {"$set": {"av": url}})
        return jsonify({"url": url})
    return jsonify({"e": "No file"}), 400

@app.route('/api/update_profile', methods=['POST'])
def update_profile():
    u = get_u()
    d = request.json
    db.users.update_one({"_id": u['_id']}, {"$set": {"name": d['name'], "bio": d['bio'], "theme": d['theme']}})
    return jsonify({"s": "ok"})

@app.route('/api/groups', methods=['GET', 'POST'])
def groups():
    u = get_u()
    if request.method == 'POST':
        gid = db.groups.insert_one({
            "title": request.json['t'], "owner": str(u['_id']),
            "admins": [str(u['_id'])], "members": [str(u['_id'])],
            "muted": [], "banned": []
        }).inserted_id
        return jsonify({"id": str(gid)})
    gs = list(db.groups.find({"members": str(u['_id'])}))
    for g in gs: g['m_count'] = len(g['members'])
    return jsonify(fix(gs))

@socketio.on('join')
def on_join(d): join_room(d['room'])

@socketio.on('typing')
def on_typing(d):
    u = get_u()
    emit('is_typing', {"uid": str(u['_id']), "name": u['name'], "room": d['room'], "st": d['st'], "is_g": d['is_g']}, room=d['room'], include_self=False)

@socketio.on('msg')
def on_msg(d):
    u = get_u()
    # Проверка на мут/бан
    if len(d['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if str(u['_id']) in g.get('banned', []): return
        if str(u['_id']) in g.get('muted', []): 
            emit('error', 'Вы в муте', to=request.sid)
            return

    m = {"room": d['room'], "sid": str(u['_id']), "name": u['name'], "av": u['av'], 
         "txt": d.get('txt'), "type": d.get('type', 'text'), "url": d.get('url'), 
         "reactions": {}, "ts": datetime.datetime.utcnow().isoformat()}
    m['_id'] = str(db.messages.insert_one(m).inserted_id)
    emit('new_msg', m, room=d['room'])

@socketio.on('call_init')
def on_call(d):
    u = get_u()
    emit('incoming_call', {"from": u['name'], "room": d['room'], "sid": str(u['_id'])}, room=d['room'], include_self=False)

@socketio.on('del_msg')
def on_del(d):
    u = get_u()
    m = db.messages.find_one({"_id": ObjectId(d['mid'])})
    if not m: return
    is_adm = False
    if len(m['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(m['room'])})
        if str(u['_id']) in g.get('admins', []): is_adm = True
    
    if m['sid'] == str(u['_id']) or is_adm:
        db.messages.delete_one({"_id": ObjectId(d['mid'])})
        emit('msg_deleted', d['mid'], room=m['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
