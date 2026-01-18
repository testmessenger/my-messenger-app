import os
from gevent import monkey
monkey.patch_all()  # Важно для стабильности сокетов на Render

import datetime
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_CORE_2024'

# --- НАСТРОЙКА ХРАНИЛИЩА ---
UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- ПОДКЛЮЧЕНИЕ К MONGODB ---
# Замени строку подключения на свою, если нужно
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority")
db = client['messenger_db']

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent', max_http_buffer_size=20000000)

# Хранилище активных соединений (sid -> user_id)
online_users = {}

def get_current_user():
    if 'user_id' not in session: return None
    return db.users.find_one({"_id": ObjectId(session['user_id'])})

def fix_id(obj):
    if isinstance(obj, list):
        for i in obj: i['_id'] = str(i['_id'])
    elif obj:
        obj['_id'] = str(obj['_id'])
    return obj

# --- РОУТЫ (API И ИНТЕРФЕЙС) ---

@app.route('/')
def index():
    user = get_current_user()
    if not user: return redirect('/auth')
    return render_template('index.html', user=fix_id(user))

@app.route('/auth')
def auth():
    return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def handle_auth():
    data = request.json
    username = data.get('username').lower().strip()
    password = data.get('pw')
    
    user = db.users.find_one({"username": username})
    
    if data.get('reg'): # Регистрация
        if user: return jsonify({"err": "Этот @username уже занят"}), 400
        user_id = db.users.insert_one({
            "username": username,
            "pw": generate_password_hash(password),
            "name": username,
            "bio": "Привет! Я в Nexus.",
            "av": "/static/default_avatar.png",
            "theme": "dark",
            "is_online": False,
            "last_seen": "был(а) недавно"
        }).inserted_id
        session['user_id'] = str(user_id)
    else: # Вход
        if user and check_password_hash(user['pw'], password):
            session['user_id'] = str(user['_id'])
        else:
            return jsonify({"err": "Неверные данные"}), 401
    return jsonify({"ok": True})

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    user = get_current_user()
    if not user: return "Unauthorized", 401
    
    data = request.form
    update_data = {
        "name": data.get('name', user['name']),
        "bio": data.get('bio', user['bio']),
        "theme": data.get('theme', user['theme'])
    }
    
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file.filename != '':
            filename = secure_filename(f"{user['_id']}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            update_data['av'] = f"/static/uploads/{filename}"
            
    db.users.update_one({"_id": user['_id']}, {"$set": update_data})
    return jsonify({"ok": True, "av": update_data.get('av', user['av'])})

@app.route('/api/search')
def search():
    q = request.args.get('q', '').lower()
    if not q: return jsonify([])
    users = list(db.users.find({"username": {"$regex": q}}, {"pw": 0}))
    groups = list(db.groups.find({"title": {"$regex": q}}))
    return jsonify({"users": fix_id(users), "groups": fix_id(groups)})

@app.route('/api/groups', methods=['GET', 'POST'])
def handle_groups():
    user = get_current_user()
    if not user: return "401", 401
    
    if request.method == 'POST':
        group_id = db.groups.insert_one({
            "title": request.json['title'],
            "owner": str(user['_id']),
            "admins": [str(user['_id'])],
            "members": [str(user['_id'])],
            "muted": [], "banned": []
        }).inserted_id
        return jsonify({"id": str(group_id)})
    
    groups = list(db.groups.find({"members": str(user['_id'])}))
    # Считаем участников и подтягиваем детали
    for g in groups:
        g['m_count'] = len(g['members'])
        g['member_list'] = fix_id(list(db.users.find({"_id": {"$in": [ObjectId(m) for m in g['members']]}}, {"pw":0})))
    return jsonify(fix_id(groups))

# --- SOCKET EVENTS (РЕАЛЬНОЕ ОБЩЕНИЕ) ---

@socketio.on('connect')
def connect():
    user = get_current_user()
    if user:
        uid = str(user['_id'])
        online_users[request.sid] = uid
        db.users.update_one({"_id": user['_id']}, {"$set": {"is_online": True, "last_seen": "в сети"}})
        emit('user_status', {"uid": uid, "status": "в сети"}, broadcast=True)

@socketio.on('disconnect')
def disconnect():
    uid = online_users.get(request.sid)
    if uid:
        now = datetime.datetime.now().strftime("%H:%M")
        status = f"был(а) в {now}"
        db.users.update_one({"_id": ObjectId(uid)}, {"$set": {"is_online": False, "last_seen": status}})
        emit('user_status', {"uid": uid, "status": status}, broadcast=True)
        online_users.pop(request.sid, None)

@socketio.on('join')
def on_join(data):
    join_room(data['room'])

@socketio.on('typing')
def on_typing(data):
    user = get_current_user()
    if user:
        # Логика по твоему запросу:
        # Если группа: "Ник печатает", если ЛС: "печатает"
        msg = f"{user['name']} печатает..." if data.get('is_group') else "печатает..."
        emit('display_typing', {"room": data['room'], "msg": msg, "uid": str(user['_id'])}, room=data['room'], include_self=False)

@socketio.on('send_msg')
def message(data):
    user = get_current_user()
    if not user: return
    
    room_id = data['room']
    
    # ПРОВЕРКА МУТА И БАНА (если это группа)
    if len(room_id) == 24:
        group = db.groups.find_one({"_id": ObjectId(room_id)})
        if group:
            if str(user['_id']) in group.get('banned', []): return
            if str(user['_id']) in group.get('muted', []):
                emit('error_alert', {"msg": "Вы в муте администратором"}, room=request.sid)
                return

    msg_obj = {
        "room": room_id,
        "sender_id": str(user['_id']),
        "sender_name": user['name'],
        "sender_av": user['av'],
        "text": data.get('text'),
        "type": data.get('type', 'text'), # text, file, circle, voice
        "url": data.get('url'), # для медиа
        "ts": datetime.datetime.now().isoformat(),
        "reacts": {}
    }
    msg_id = db.messages.insert_one(msg_obj).inserted_id
    msg_obj['_id'] = str(msg_id)
    
    emit('new_msg', msg_obj, room=room_id)

@socketio.on('add_react')
def react(data):
    # data: mid (message id), emoji
    user = get_current_user()
    db.messages.update_one(
        {"_id": ObjectId(data['mid'])},
        {"$set": {f"reacts.{str(user['_id'])}": data['emoji']}}
    )
    emit('update_reacts', data, room=data['room'])

@socketio.on('delete_msg')
def delete(data):
    user = get_current_user()
    msg = db.messages.find_one({"_id": ObjectId(data['mid'])})
    if not msg: return
    
    # Права: автор сообщения или админ группы
    can_delete = (msg['sender_id'] == str(user['_id']))
    if not can_delete and len(data['room']) == 24:
        group = db.groups.find_one({"_id": ObjectId(data['room'])})
        if str(user['_id']) in group.get('admins', []):
            can_delete = True
            
    if can_delete:
        db.messages.delete_one({"_id": ObjectId(data['mid'])})
        emit('msg_deleted', {"mid": data['mid']}, room=data['room'])

@socketio.on('admin_action')
def admin(data):
    # data: room, target_id, action (ban, mute, promote, delete_chat)
    user = get_current_user()
    group = db.groups.find_one({"_id": ObjectId(data['room'])})
    
    if not group or str(user['_id']) not in group['admins']: return
    
    target = data['target_id']
    if data['action'] == 'ban':
        db.groups.update_one({"_id": group['_id']}, {"$addToSet": {"banned": target}, "$pull": {"members": target}})
        emit('kicked', {"uid": target}, room=data['room'])
    elif data['action'] == 'mute':
        db.groups.update_one({"_id": group['_id']}, {"$addToSet": {"muted": target}})
    elif data['action'] == 'promote':
        db.groups.update_one({"_id": group['_id']}, {"$addToSet": {"admins": target}})
    elif data['action'] == 'delete_chat' and group['owner'] == str(user['_id']):
        db.groups.delete_one({"_id": group['_id']})
        db.messages.delete_many({"room": data['room']})
        emit('chat_closed', {}, room=data['room'])

@socketio.on('call_init')
def call(data):
    user = get_current_user()
    # Шлём сигнал "входящий звонок" с данными звонящего
    emit('incoming_call', {
        "room": data['room'],
        "caller_name": user['name'],
        "caller_av": user['av'],
        "type": data['type'] # audio/video
    }, room=data['room'], include_self=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
