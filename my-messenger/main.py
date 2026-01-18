import eventlet
eventlet.monkey_patch()
import datetime, base64, json
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_MAX_2026'

client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true")
db = client['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=20000000)

def get_u():
    u = db.users.find_one({"_id": ObjectId(session['user_id'])}) if 'user_id' in session else None
    if u: # Обновляем статус "В сети" при любом запросе
        db.users.update_one({"_id": u['_id']}, {"$set": {"last_seen": datetime.datetime.utcnow().isoformat()}})
    return u

# --- АВТОРИЗАЦИЯ ---
@app.route('/api/auth', methods=['POST'])
def auth():
    d = request.json
    if d.get('reg'):
        if db.users.find_one({"username": d['username']}): return jsonify({"e": "Ник занят"}), 400
        uid = db.users.insert_one({
            "username": d['username'], "pw": generate_password_hash(d['pw']),
            "name": d['username'], "avatar": "https://cdn-icons-png.flaticon.com/512/149/149071.png",
            "bio": "Nexus User", "theme": "dark", "last_seen": datetime.datetime.utcnow().isoformat()
        }).inserted_id
        session['user_id'] = str(uid)
    else:
        u = db.users.find_one({"username": d['username']})
        if u and check_password_hash(u['pw'], d['pw']): session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Ошибка"}), 401
    return jsonify({"s": "ok"})

# --- АДМИНКА И ГРУППЫ ---
@app.route('/api/groups', methods=['POST', 'GET', 'DELETE'])
def groups_api():
    u = get_u()
    if request.method == 'POST':
        gid = db.groups.insert_one({"title": request.json['t'], "owner": str(u['_id']), "admins": [str(u['_id'])], "members": [str(u['_id'])], "banned": [], "muted": []}).inserted_id
        return jsonify({"id": str(gid)})
    if request.method == 'GET':
        gs = list(db.groups.find({"members": str(u['_id'])}))
        for g in gs: g['_id'] = str(g['_id'])
        return jsonify(gs)
    if request.method == 'DELETE':
        g = db.groups.find_one({"_id": ObjectId(request.json['gid'])})
        if g and g['owner'] == str(u['_id']):
            db.groups.delete_one({"_id": g['_id']})
            db.messages.delete_many({"room": str(g['_id'])})
            return "ok"
        return "403", 403

# --- ПРОФИЛЬ И ИСТОРИЯ ---
@app.route('/api/history/<rid>')
def history(rid):
    ms = list(db.messages.find({"room": rid}).sort("ts", -1).limit(50))
    for m in ms: m['_id'] = str(m['_id'])
    return jsonify(ms[::-1])

@app.route('/api/user/<uid>')
def get_user_info(uid):
    u = db.users.find_one({"_id": ObjectId(uid)}, {"pw": 0})
    if u: u['_id'] = str(u['_id'])
    return jsonify(u)

@app.route('/')
def main():
    u = get_u()
    return render_template('index.html', user=u) if u else redirect('/auth')

@app.route('/auth')
def auth_pg(): return render_template('auth.html')

# --- SOCKETS (Status, Typing, Messages) ---
@socketio.on('join')
def on_j(d):
    join_room(d['room'])

@socketio.on('typing')
def on_typing(d):
    u = get_u()
    # d['is_group'] определяет, что показывать: "Ник печатает" или просто "печатает"
    emit('display_typing', {"name": u['name'], "room": d['room'], "is_group": d['is_group'], "state": d['state']}, room=d['room'], include_self=False)

@socketio.on('msg')
def handle_m(d):
    u = get_u()
    # Проверка мута
    if len(d['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if g and str(u['_id']) in g.get('muted', []): return
    
    msg = {"room": d['room'], "sid": str(u['_id']), "name": u['name'], "av": u['avatar'], "txt": d.get('txt'), "type": d.get('type', 'text'), "url": d.get('url'), "reacts": {}, "ts": datetime.datetime.utcnow().isoformat()}
    msg['_id'] = str(db.messages.insert_one(msg).inserted_id)
    emit('new_msg', msg, room=d['room'])

@socketio.on('del_msg')
def del_m(d):
    u = get_u()
    m = db.messages.find_one({"_id": ObjectId(d['mid'])})
    if m['sid'] == str(u['_id']):
        db.messages.delete_one({"_id": ObjectId(d['mid'])})
        emit('msg_del', d['mid'], room=m['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
