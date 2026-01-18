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
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_CORE_2026'

# Хранилище
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Подключение к MongoDB (Исправлено для Render/Gevent)
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority", connect=False)
db = client['messenger_db']

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent', max_http_buffer_size=25000000)

online_users = {} # sid -> uid

def get_current_user():
    if 'user_id' not in session: return None
    return db.users.find_one({"_id": ObjectId(session['user_id'])})

def fix_id(obj):
    if isinstance(obj, list):
        for i in obj: i['_id'] = str(i['_id'])
    elif obj:
        obj['_id'] = str(obj['_id'])
    return obj

# --- API ---

@app.route('/')
def index():
    user = get_current_user()
    if not user: return redirect('/auth')
    return render_template('index.html', user=fix_id(user))

@app.route('/auth')
def auth(): return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def handle_auth():
    data = request.json
    username = data.get('username', '').lower().strip()
    password = data.get('pw')
    user = db.users.find_one({"username": username})
    
    if data.get('reg'):
        if user: return jsonify({"err": "Username занят"}), 400
        uid = db.users.insert_one({
            "username": username, "pw": generate_password_hash(password),
            "name": username, "bio": "Я в Nexus!", "av": "/static/default.png",
            "theme": "dark", "is_online": False, "last_seen": "недавно"
        }).inserted_id
        session['user_id'] = str(uid)
    else:
        if user and check_password_hash(user['pw'], password):
            session['user_id'] = str(user['_id'])
        else: return jsonify({"err": "Неверные данные"}), 401
    return jsonify({"ok": True})

@app.route('/api/history/<room_id>')
def get_history(room_id):
    if 'user_id' not in session: return "401", 401
    msgs = list(db.messages.find({"room": room_id}).sort("ts", 1).limit(50))
    return jsonify(fix_id(msgs))

@app.route('/api/groups', methods=['GET', 'POST'])
def handle_groups():
    user = get_current_user()
    if not user: return "401", 401
    if request.method == 'POST':
        gid = db.groups.insert_one({
            "title": request.json['title'], "owner": str(user['_id']),
            "admins": [str(user['_id'])], "members": [str(user['_id'])],
            "muted": [], "banned": []
        }).inserted_id
        return jsonify({"id": str(gid)})
    
    groups = list(db.groups.find({"members": str(user['_id'])}))
    for g in groups:
        g['member_list'] = fix_id(list(db.users.find({"_id": {"$in": [ObjectId(m) for m in g['members']]}}, {"pw":0})))
    return jsonify(fix_id(groups))

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    user = get_current_user()
    if not user: return "401", 401
    if request.is_json:
        db.users.update_one({"_id": user['_id']}, {"$set": {"theme": request.json.get('theme')}})
        return jsonify({"ok": True})
    
    update_data = {"name": request.form.get('name'), "bio": request.form.get('bio')}
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file.filename != '':
            fname = secure_filename(f"{user['_id']}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            update_data['av'] = f"/static/uploads/{fname}"
    db.users.update_one({"_id": user['_id']}, {"$set": update_data})
    return jsonify({"ok": True})

# --- SOCKETS ---

@socketio.on('connect')
def connect():
    user = get_current_user()
    if user:
        online_users[request.sid] = str(user['_id'])
        db.users.update_one({"_id": user['_id']}, {"$set": {"is_online": True, "last_seen": "в сети"}})
        emit('user_status', {"uid": str(user['_id']), "status": "в сети"}, broadcast=True)

@socketio.on('disconnect')
def disconnect():
    uid = online_users.get(request.sid)
    if uid:
        now = datetime.datetime.now().strftime("%H:%M")
        db.users.update_one({"_id": ObjectId(uid)}, {"$set": {"is_online": False, "last_seen": f"был(а) в {now}"}})
        emit('user_status', {"uid": uid, "status": f"был(а) в {now}"}, broadcast=True)
        online_users.pop(request.sid, None)

@socketio.on('join')
def on_join(data): join_room(data['room'])

@socketio.on('typing')
def on_typing(data):
    user = get_current_user()
    if user:
        # Статус: Ник печатает (группа) или просто печатает (ЛС)
        txt = f"{user['name']} печатает..." if data.get('is_g') else "печатает..."
        emit('typing_ev', {"room": data['room'], "msg": txt, "st": data['st'], "uid": str(user['_id'])}, room=data['room'], include_self=False)

@socketio.on('send_msg')
def handle_msg(data):
    user = get_current_user()
    if not user: return
    
    # Проверка мута/бана в группе
    if len(data['room']) == 24:
        group = db.groups.find_one({"_id": ObjectId(data['room'])})
        if group:
            if str(user['_id']) in group.get('banned', []): return
            if str(user['_id']) in group.get('muted', []):
                emit('error_alert', {"msg": "Вы в муте"}, room=request.sid)
                return

    msg_obj = {
        "room": data['room'], "sid": str(user['_id']), "name": user['name'],
        "av": user['av'], "txt": data.get('text'), "type": data.get('type', 'text'),
        "url": data.get('url'), "ts": datetime.datetime.now().isoformat(), "reacts": {}
    }
    msg_id = db.messages.insert_one(msg_obj).inserted_id
    msg_obj['_id'] = str(msg_id)
    emit('new_msg', msg_obj, room=data['room'])

@socketio.on('delete_msg')
def delete(data):
    user = get_current_user()
    msg = db.messages.find_one({"_id": ObjectId(data['mid'])})
    if not msg: return
    can_del = (msg['sid'] == str(user['_id']))
    if not can_del:
        group = db.groups.find_one({"_id": ObjectId(msg['room'])})
        if group and str(user['_id']) in group.get('admins', []): can_del = True
    if can_del:
        db.messages.delete_one({"_id": ObjectId(data['mid'])})
        emit('msg_deleted', {"mid": data['mid']}, room=msg['room'])

@socketio.on('call_init')
def call(data):
    user = get_current_user()
    emit('incoming_call', {
        "room": data['room'], "from_name": user['name'], 
        "from_av": user['av'], "type": data['type']
    }, room=data['room'], include_self=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
