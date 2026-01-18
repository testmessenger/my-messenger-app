import os
from gevent import monkey
monkey.patch_all()

import datetime
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_2026_SECURE'

# Исправление ошибки создания папок на Render
UPLOAD_FOLDER = os.path.join('static', 'uploads')
if os.path.exists(UPLOAD_FOLDER) and not os.path.isdir(UPLOAD_FOLDER):
    os.remove(UPLOAD_FOLDER)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Подключение к MongoDB
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority", connect=False)
db = client['messenger_db']

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent', max_http_buffer_size=50000000)

online_users = {} # sid -> uid

def get_current_user():
    if 'user_id' not in session: return None
    try:
        return db.users.find_one({"_id": ObjectId(session['user_id'])})
    except: return None

def fix_id(obj):
    if isinstance(obj, list):
        for i in obj: i['_id'] = str(i['_id'])
    elif obj: obj['_id'] = str(obj['_id'])
    return obj

# --- API ЭНДПОИНТЫ ---

@app.route('/')
def index():
    user = get_current_user()
    if not user: return redirect('/auth')
    return render_template('index.html', user=fix_id(user))

@app.route('/auth')
def auth_page(): return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def handle_auth():
    data = request.json
    un = data.get('username', '').lower().strip()
    user = db.users.find_one({"username": un})
    if data.get('reg'):
        if user: return jsonify({"err": "Username занят"}), 400
        uid = db.users.insert_one({
            "username": un, "pw": generate_password_hash(data['pw']),
            "name": un, "bio": "Я в Nexus!", "av": "/static/default.png",
            "theme": "dark", "is_online": False, "last_seen": "был(а) недавно"
        }).inserted_id
        session['user_id'] = str(uid)
    else:
        if user and check_password_hash(user['pw'], data['pw']):
            session['user_id'] = str(user['_id'])
        else: return jsonify({"err": "Неверный логин/пароль"}), 401
    return jsonify({"ok": True})

@app.route('/api/profile', methods=['POST'])
def update_profile():
    user = get_current_user()
    if not user: return "401", 401
    upd = {"name": request.form.get('name'), "bio": request.form.get('bio'), "theme": request.form.get('theme')}
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file.filename:
            fname = secure_filename(f"{user['_id']}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            upd['av'] = f"/static/uploads/{fname}"
    db.users.update_one({"_id": user['_id']}, {"$set": upd})
    return jsonify({"ok": True})

@app.route('/api/groups', methods=['GET', 'POST'])
def handle_groups():
    user = get_current_user()
    if request.method == 'POST':
        gid = db.groups.insert_one({
            "title": request.json['title'], "owner": str(user['_id']),
            "admins": [str(user['_id'])], "members": [str(user['_id'])],
            "muted": [], "banned": []
        }).inserted_id
        return jsonify({"id": str(gid)})
    groups = list(db.groups.find({"members": str(user['_id'])}))
    return jsonify(fix_id(groups))

# --- SOCKET.IO ЛОГИКА ---

@socketio.on('connect')
def connect():
    user = get_current_user()
    if user:
        online_users[request.sid] = str(user['_id'])
        db.users.update_one({"_id": user['_id']}, {"$set": {"is_online": True, "last_seen": "в сети"}})
        emit('user_status', {"uid": str(user['_id']), "st": "в сети"}, broadcast=True)

@socketio.on('disconnect')
def disconnect():
    uid = online_users.get(request.sid)
    if uid:
        time = datetime.datetime.now().strftime("%H:%M")
        db.users.update_one({"_id": ObjectId(uid)}, {"$set": {"is_online": False, "last_seen": f"был(а) в {time}"}})
        emit('user_status', {"uid": uid, "st": f"был(а) в {time}"}, broadcast=True)

@socketio.on('typing')
def on_typing(data):
    user = get_current_user()
    # В группе: "Ник печатает", в ЛС: "печатает"
    msg = f"{user['name']} печатает..." if data.get('is_g') else "печатает..."
    emit('typing_ev', {"room": data['room'], "msg": msg, "st": data['st']}, room=data['room'], include_self=False)

@socketio.on('send_msg')
def handle_msg(data):
    user = get_current_user()
    room = data['room']
    
    # Проверка мута
    group = db.groups.find_one({"_id": ObjectId(room)}) if len(room) == 24 else None
    if group and str(user['_id']) in group.get('muted', []):
        emit('error_alert', "Вы в муте", room=request.sid)
        return

    msg = {
        "room": room, "sid": str(user['_id']), "name": user['name'], "av": user['av'],
        "txt": data.get('text'), "type": data.get('type', 'text'), 
        "file": data.get('file_url'), "ts": datetime.datetime.now().isoformat(), "reacts": {}
    }
    mid = db.messages.insert_one(msg).inserted_id
    msg['_id'] = str(mid)
    emit('new_msg', msg, room=room)

@socketio.on('call_init')
def call(data):
    user = get_current_user()
    emit('incoming_call', {"room": data['room'], "from": user['name'], "av": user['av']}, room=data['room'], include_self=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
