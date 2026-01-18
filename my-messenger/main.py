import os
from gevent import monkey
monkey.patch_all() # Обязательно на самом верху для стабильности сокетов

import datetime
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_CORE_2026'

# --- НАСТРОЙКА ХРАНИЛИЩА (Для аватаров и файлов) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_PATH = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_PATH, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_PATH

# --- БАЗА ДАННЫХ ---
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true")
db = client['messenger_db']

# SocketIO с поддержкой Gevent для работы на Render без вылетов
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent', max_http_buffer_size=100000000)

online_users = {} # sid: uid

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

# --- МАРШРУТЫ И API ---

@app.route('/')
def index():
    u = get_u()
    if not u: return redirect('/auth')
    return render_template('index.html', user=fix(u))

@app.route('/auth')
def auth():
    return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def handle_auth():
    d = request.json
    u = db.users.find_one({"username": d['username']})
    if d.get('reg'):
        if u: return jsonify({"e": "Ник занят"}), 400
        uid = db.users.insert_one({
            "username": d['username'], "pw": generate_password_hash(d['pw']),
            "name": d['username'], "av": "/static/default.png", "bio": "Nexus User",
            "theme": "dark", "is_online": False, "last_seen": "был(а) недавно"
        }).inserted_id
        session['user_id'] = str(uid)
    else:
        if u and check_password_hash(u['pw'], d['pw']): 
            session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Ошибка входа"}), 401
    return jsonify({"s": "ok"})

@app.route('/api/search')
def search():
    q = request.args.get('q', '').replace('@', '')
    if not q: return jsonify({"users": [], "groups": []})
    users = list(db.users.find({"username": {"$regex": q, "$options": "i"}}, {"pw":0}))
    groups = list(db.groups.find({"title": {"$regex": q, "$options": "i"}}))
    return jsonify({"users": fix(users), "groups": fix(groups)})

@app.route('/api/groups', methods=['GET', 'POST'])
def handle_groups():
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
        m_list = list(db.users.find({"_id": {"$in": [ObjectId(m) for m in g['members']]}}, {"pw":0}))
        g['member_details'] = fix(m_list)
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
    # Загружаем последние 50 сообщений
    return jsonify(fix(list(db.messages.find({"room": rid}).sort("ts", -1).limit(50))[::-1]))

# --- SOCKETS (РЕАЛЬНОЕ ВРЕМЯ) ---

@socketio.on('connect')
def on_connect():
    u = get_u()
    if u:
        uid = str(u['_id'])
        online_users[request.sid] = uid
        db.users.update_one({"_id": u['_id']}, {"$set": {"is_online": True}})
        emit('status_ev', {"uid": uid, "on": True}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    uid = online_users.get(request.sid)
    if uid:
        last = datetime.datetime.now().strftime("%H:%M")
        status = f"был(а) в {last}"
        db.users.update_one({"_id": ObjectId(uid)}, {"$set": {"is_online": False, "last_seen": status}})
        emit('status_ev', {"uid": uid, "on": False, "last": status}, broadcast=True)
        online_users.pop(request.sid, None)

@socketio.on('join')
def on_join(d): 
    join_room(d['room'])

@socketio.on('typing')
def on_typing(d):
    u = get_u()
    if u:
        # В группе шлем "Имя печатает", в ЛС - "печатает"
        emit('typing_ev', {
            "name": u['name'], "room": d['room'], 
            "st": d['st'], "is_g": d['is_g']
        }, room=d['room'], include_self=False)

@socketio.on('msg')
def on_msg(d):
    u = get_u()
    if not u: return
    
    # ПРОВЕРКА БАНА И МУТА
    if len(d['room']) == 24: # ID группы
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if g:
            if str(u['_id']) in g.get('banned', []): return
            if str(u['_id']) in g.get('muted', []): 
                emit('error_ev', {"m": "Вы в муте"}, room=request.sid)
                return

    m = {
        "room": d['room'], "sid": str(u['_id']), "name": u['name'], "av": u['av'],
        "txt": d.get('txt'), "type": d.get('type', 'text'), "url": d.get('url'),
        "ts": datetime.datetime.now().isoformat(), "reacts": {}
    }
    m['_id'] = str(db.messages.insert_one(m).inserted_id)
    emit('new_msg', m, room=d['room'])

@socketio.on('react')
def on_react(d):
    # d: mid, emoji, uid, room
    db.messages.update_one({"_id": ObjectId(d['mid'])}, {"$set": {f"reacts.{d['uid']}": d['emoji']}})
    emit('update_reacts', d, room=d['room'])

@socketio.on('call_init')
def on_call(d):
    u = get_u()
    if u:
        emit('incoming_call', {
            "from": u['name'], "av": u['av'], 
            "room": d['room'], "uid": str(u['_id'])
        }, room=d['room'], include_self=False)

@socketio.on('delete_msg')
def on_delete(d):
    u = get_u()
    msg = db.messages.find_one({"_id": ObjectId(d['mid'])})
    if not msg: return
    
    is_adm = False
    if len(d['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if g and str(u['_id']) in g.get('admins', []): is_adm = True
        
    if str(u['_id']) == msg['sid'] or is_adm:
        db.messages.delete_one({"_id": ObjectId(d['mid'])})
        emit('msg_deleted', d['mid'], room=d['room'])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)
