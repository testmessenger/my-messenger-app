import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_2026'

# Подключение к MongoDB
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true")
db = client['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=10000000)

def fix(d):
    if not d: return d
    if isinstance(d, list):
        for i in d: i['_id'] = str(i['_id'])
    else: d['_id'] = str(d['_id'])
    return d

def get_u():
    if 'user_id' not in session: return None
    # Обновляем время последнего визита при каждом запросе (был недавно)
    u = db.users.find_one({"_id": ObjectId(session['user_id'])})
    if u:
        db.users.update_one({"_id": u['_id']}, {"$set": {"last_seen": datetime.datetime.utcnow().isoformat()}})
    return u

@app.route('/')
def index():
    return render_template('index.html', user=fix(get_u())) if 'user_id' in session else redirect('/auth')

@app.route('/api/auth', methods=['POST'])
def handle_auth():
    d = request.json
    if d.get('reg'):
        if db.users.find_one({"username": d['username']}): return jsonify({"e": "Ник занят"}), 400
        uid = db.users.insert_one({
            "username": d['username'], 
            "pw": generate_password_hash(d['pw']), 
            "name": d['username'], 
            "av": "https://ui-avatars.com/api/?name="+d['username'], 
            "bio": "Nexus User", 
            "theme": "dark",
            "last_seen": datetime.datetime.utcnow().isoformat()
        }).inserted_id
        session['user_id'] = str(uid)
    else:
        u = db.users.find_one({"username": d['username']})
        if u and check_password_hash(u['pw'], d['pw']): session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Ошибка"}), 401
    return jsonify({"s": "ok"})

@app.route('/api/search_global/<q>')
def search_global(q):
    users = list(db.users.find({"username": {"$regex": q, "$options": "i"}}, {"pw": 0}))
    return jsonify(fix(users))

@app.route('/api/groups', methods=['GET', 'POST'])
def groups():
    u = get_u()
    if request.method == 'POST':
        gid = db.groups.insert_one({
            "title": request.json['t'], 
            "owner": str(u['_id']), 
            "admins": [str(u['_id'])], 
            "members": [str(u['_id'])], 
            "muted": [], "banned": []
        }).inserted_id
        return jsonify({"id": str(gid)})
    return jsonify(fix(list(db.groups.find({"members": str(u['_id'])}))))

@app.route('/api/group_members/<gid>')
def group_members(gid):
    g = db.groups.find_one({"_id": ObjectId(gid)})
    users = list(db.users.find({"_id": {"$in": [ObjectId(m) for m in g['members']]}}, {"pw": 0}))
    return jsonify(fix(users))

@app.route('/api/history/<rid>')
def history(rid):
    # Подгружаем последние 50 сообщений
    msgs = list(db.messages.find({"room": rid}).sort("ts", -1).limit(50))
    return jsonify(fix(msgs[::-1]))

@socketio.on('join')
def join(d): 
    join_room(d['room'])

@socketio.on('typing')
def typing(d):
    u = get_u()
    # d['st'] - статус печатает (true/false), d['is_g'] - группа или лс
    emit('is_typing', {"uid": str(u['_id']), "name": u['name'], "room": d['room'], "st": d['st'], "is_g": d['is_g']}, room=d['room'], include_self=False)

@socketio.on('msg')
def msg(d):
    u = get_u()
    # Проверка на мут в группах
    if len(d['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if g and str(u['_id']) in g.get('muted', []): return
    
    m = {
        "room": d['room'], "sid": str(u['_id']), "name": u['name'], 
        "av": u['av'], "txt": d.get('txt'), "type": d.get('type', 'text'), 
        "url": d.get('url'), "reacts": {}, "ts": datetime.datetime.utcnow().isoformat()
    }
    m['_id'] = str(db.messages.insert_one(m).inserted_id)
    emit('new_msg', m, room=d['room'])

@socketio.on('call_init')
def call_init(d):
    u = get_u()
    emit('incoming_call', {"from": u['name'], "room": d['room'], "sid": str(u['_id'])}, room=d['room'], include_self=False)

@socketio.on('del_msg')
def del_msg(d):
    u = get_u()
    m = db.messages.find_one({"_id": ObjectId(d['mid'])})
    if not m: return
    # Удалять может автор или админ (если это группа)
    can_del = (m['sid'] == str(u['_id']))
    if not can_del and len(m['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(m['room'])})
        if str(u['_id']) in g.get('admins', []): can_del = True
    
    if can_del:
        db.messages.delete_one({"_id": ObjectId(d['mid'])})
        emit('msg_deleted', d['mid'], room=m['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
