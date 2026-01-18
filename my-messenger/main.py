import eventlet
eventlet.monkey_patch()
import datetime, base64, json
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTRA_CORE_2026'

# База данных (Твой URI)
client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true")
db = client['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=20000000)

def get_u():
    return db.users.find_one({"_id": ObjectId(session['user_id'])}) if 'user_id' in session else None

# --- АВТОРИЗАЦИЯ (MongoDB) ---
@app.route('/api/auth', methods=['POST'])
def auth():
    d = request.json
    if d.get('reg'):
        if db.users.find_one({"username": d['username']}): return jsonify({"e": "Ник занят"}), 400
        uid = db.users.insert_one({"username": d['username'], "pw": generate_password_hash(d['pw']), "name": d['username'], "avatar": "https://cdn-icons-png.flaticon.com/512/149/149071.png", "bio": "Nexus User", "theme": "dark"}).inserted_id
        session['user_id'] = str(uid)
    else:
        u = db.users.find_one({"username": d['username']})
        if u and check_password_hash(u['pw'], d['pw']): session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Ошибка"}), 401
    return jsonify({"s": "ok"})

# --- УПРАВЛЕНИЕ ГРУППАМИ И АДМИНКА ---
@app.route('/api/groups', methods=['POST', 'GET', 'DELETE'])
def groups():
    u = get_u()
    if request.method == 'POST': # Создание
        gid = db.groups.insert_one({"title": request.json['t'], "owner": str(u['_id']), "admins": [str(u['_id'])], "members": [str(u['_id'])], "banned": [], "muted": []}).inserted_id
        return jsonify({"id": str(gid)})
    if request.method == 'GET': # Список чатов
        gs = list(db.groups.find({"members": str(u['_id'])}))
        for g in gs: g['_id'] = str(g['_id'])
        return jsonify(gs)
    if request.method == 'DELETE': # Удаление группы (Только владелец)
        g = db.groups.find_one({"_id": ObjectId(request.json['gid'])})
        if g['owner'] == str(u['_id']):
            db.groups.delete_one({"_id": g['_id']})
            db.messages.delete_many({"room": str(g['_id'])})
            return "ok"
        return "403", 403

# --- АДМИН-ДЕЙСТВИЯ (Бан, Мут, Права) ---
@app.route('/api/admin', methods=['POST'])
def admin():
    u = get_u()
    d = request.json # gid, target, act
    g = db.groups.find_one({"_id": ObjectId(d['gid'])})
    if str(u['_id']) not in g['admins']: return "Error", 403
    
    if d['act'] == 'ban':
        db.groups.update_one({"_id": g['_id']}, {"$pull": {"members": d['target']}, "$push": {"banned": d['target']}})
    elif d['act'] == 'mute':
        db.groups.update_one({"_id": g['_id']}, {"$push": {"muted": d['target']}})
    elif d['act'] == 'promote' and g['owner'] == str(u['_id']):
        db.groups.update_one({"_id": g['_id']}, {"$push": {"admins": d['target']}})
    return "ok"

# --- ПРОФИЛЬ И ИСТОРИЯ ---
@app.route('/api/profile', methods=['POST'])
def profile():
    db.users.update_one({"_id": get_u()['_id']}, {"$set": request.json})
    return "ok"

@app.route('/api/history/<rid>')
def history(rid):
    ms = list(db.messages.find({"room": rid}).sort("ts", -1).limit(50))
    for m in ms: m['_id'] = str(m['_id'])
    return jsonify(ms[::-1])

@app.route('/')
def main():
    u = get_u()
    return render_template('index.html', user=u) if u else redirect('/auth')

@app.route('/auth')
def auth_pg(): return render_template('auth.html')

# --- SOCKETS (Мультимедиа, Реакции, Удаление) ---
@socketio.on('join')
def on_j(d):
    u = get_u()
    g = db.groups.find_one({"_id": ObjectId(d['room'])})
    if g and str(u['_id']) in g['banned']: return
    join_room(d['room'])

@socketio.on('msg')
def handle_m(d):
    u = get_u()
    g = db.groups.find_one({"_id": ObjectId(d['room'])})
    if g and str(u['_id']) in g.get('muted', []):
        emit('error', 'Вы в муте', room=request.sid)
        return
    
    msg = {"room": d['room'], "sid": str(u['_id']), "name": u['name'], "av": u['avatar'], "txt": d.get('txt'), "type": d.get('type', 'text'), "url": d.get('url'), "reacts": {}, "ts": datetime.datetime.utcnow().isoformat()}
    msg['_id'] = str(db.messages.insert_one(msg).inserted_id)
    emit('new_msg', msg, room=d['room'])

@socketio.on('del_msg')
def del_m(d):
    u = get_u()
    m = db.messages.find_one({"_id": ObjectId(d['mid'])})
    g = db.groups.find_one({"_id": ObjectId(m['room'])})
    if m['sid'] == str(u['_id']) or (g and str(u['_id']) in g['admins']):
        db.messages.delete_one({"_id": ObjectId(d['mid'])})
        emit('msg_del', d['mid'], room=m['room'])

@socketio.on('react')
def react(d):
    db.messages.update_one({"_id": ObjectId(d['mid'])}, {"$inc": {f"reacts.{d['emoji']}": 1}})
    emit('update_reacts', d, room=d['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
