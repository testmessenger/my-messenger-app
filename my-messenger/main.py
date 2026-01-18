import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTRA_CORE_2026'

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
    if u: db.users.update_one({"_id": u['_id']}, {"$set": {"last_seen": datetime.datetime.utcnow().isoformat()}})
    return u

@app.route('/')
def index(): return render_template('index.html', user=fix(get_u())) if 'user_id' in session else redirect('/auth')
@app.route('/auth')
def auth_pg(): return render_template('auth.html')

# --- АВТОРИЗАЦИЯ И ПРОФИЛЬ ---
@app.route('/api/auth', methods=['POST'])
def handle_auth():
    d = request.json
    if d.get('reg'):
        if db.users.find_one({"username": d['username']}): return jsonify({"e": "Ник занят"}), 400
        uid = db.users.insert_one({"username": d['username'], "pw": generate_password_hash(d['pw']), "name": d['username'], "av": "https://ui-avatars.com/api/?name="+d['username'], "bio": "Nexus User", "theme": "dark"}).inserted_id
        session['user_id'] = str(uid)
    else:
        u = db.users.find_one({"username": d['username']})
        if u and check_password_hash(u['pw'], d['pw']): session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Ошибка входа"}), 401
    return jsonify({"s": "ok"})

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    db.users.update_one({"_id": get_u()['_id']}, {"$set": request.json})
    return "ok"

@app.route('/api/search_global/<q>')
def search_global(q):
    return jsonify(fix(list(db.users.find({"username": {"$regex": q, "$options": "i"}}, {"pw":0}))))

# --- ГРУППЫ И АДМИНКА ---
@app.route('/api/groups', methods=['GET', 'POST', 'DELETE'])
def manage_groups():
    u = get_u()
    if request.method == 'POST':
        gid = db.groups.insert_one({"title": request.json['t'], "owner": str(u['_id']), "admins": [str(u['_id'])], "members": [str(u['_id'])], "banned": [], "muted": []}).inserted_id
        return jsonify({"id": str(gid)})
    if request.method == 'DELETE':
        g = db.groups.find_one({"_id": ObjectId(request.json['gid'])})
        if g['owner'] == str(u['_id']):
            db.groups.delete_one({"_id": g['_id']})
            db.messages.delete_many({"room": str(g['_id'])})
        return "ok"
    gs = list(db.groups.find({"members": str(u['_id'])}))
    return jsonify(fix(gs))

@app.route('/api/admin_action', methods=['POST'])
def admin_act():
    u = get_u(); d = request.json; g = db.groups.find_one({"_id": ObjectId(d['gid'])})
    if str(u['_id']) not in g['admins']: return "Error", 403
    if d['act'] == 'ban': db.groups.update_one({"_id": g['_id']}, {"$pull": {"members": d['target']}, "$push": {"banned": d['target']}})
    if d['act'] == 'mute': db.groups.update_one({"_id": g['_id']}, {"$push": {"muted": d['target']}})
    if d['act'] == 'promote' and g['owner'] == str(u['_id']): db.groups.update_one({"_id": g['_id']}, {"$push": {"admins": d['target']}})
    return "ok"

@app.route('/api/history/<rid>')
def get_hist(rid):
    return jsonify(fix(list(db.messages.find({"room": rid}).sort("ts", -1).limit(50))[::-1]))

# --- SOCKETS (ГОЛОСОВЫЕ, ПЕЧАТАЕТ, РЕАКЦИИ) ---
@socketio.on('join')
def on_join(d): join_room(d['room'])

@socketio.on('typing')
def on_type(d):
    u = get_u()
    emit('is_typing', {"name": u['name'], "room": d['room'], "st": d['st'], "is_g": d['is_g']}, room=d['room'], include_self=False)

@socketio.on('msg')
def on_msg(d):
    u = get_u()
    if len(d['room']) == 24:
        g = db.groups.find_one({"_id": ObjectId(d['room'])})
        if str(u['_id']) in g.get('muted', []): return
    msg = {"room": d['room'], "sid": str(u['_id']), "name": u['name'], "av": u['av'], "txt": d.get('txt'), "type": d.get('type', 'text'), "url": d.get('url'), "reacts": {}, "ts": datetime.datetime.utcnow().isoformat()}
    msg['_id'] = str(db.messages.insert_one(msg).inserted_id)
    emit('new_msg', msg, room=d['room'])

@socketio.on('call_init')
def on_call(d):
    u = get_u()
    emit('incoming_call', {"from": u['name'], "room": d['room']}, room=d['room'], include_self=False)

@socketio.on('react')
def on_react(d):
    db.messages.update_one({"_id": ObjectId(d['mid'])}, {"$inc": {f"reacts.{d['emoji']}": 1}})
    emit('update_react', d, room=d['room'])

@socketio.on('del_msg')
def on_del(d):
    u = get_u(); m = db.messages.find_one({"_id": ObjectId(d['mid'])})
    if m['sid'] == str(u['_id']):
        db.messages.delete_one({"_id": ObjectId(d['mid'])})
        emit('msg_deleted', d['mid'], room=m['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
