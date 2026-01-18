import eventlet
eventlet.monkey_patch()
import datetime, base64
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nexus_infinity_2026'

# База данных
MONGO_URI = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
db = MongoClient(MONGO_URI)['messenger_db']
socketio = SocketIO(app, cors_allowed_origins="*")

def get_user():
    return db.users.find_one({"_id": ObjectId(session['user_id'])}) if 'user_id' in session else None

@app.route('/')
def index():
    u = get_user()
    return render_template('index.html', user=u) if u else redirect(url_for('auth'))

@app.route('/auth')
def auth(): return render_template('auth.html')

@app.route('/manifest.json')
def manifest():
    return jsonify({"short_name": "Nexus", "name": "Nexus Messenger", "start_url": "/", "display": "standalone", "background_color": "#020617", "theme_color": "#3b82f6", "icons": [{"src": "https://cdn-icons-png.flaticon.com/512/5968/5968756.png", "sizes": "512x512", "type": "image/png"}]})

# --- API ---
@app.route('/api/auth/action', methods=['POST'])
def auth_action():
    d = request.json
    u = db.users.find_one({"username": d['username']})
    if d.get('reg'):
        if u: return jsonify({"error": "Exists"}), 400
        uid = db.users.insert_one({"username": d['username'], "password": generate_password_hash(d['password']), "display_name": d['username'], "avatar": "https://ui-avatars.com/api/?name="+d['username'], "bio": "New user"}).inserted_id
        session['user_id'] = str(uid)
    else:
        if u and check_password_hash(u['password'], d['password']): session['user_id'] = str(u['_id'])
        else: return jsonify({"error": "Bad login"}), 401
    return jsonify({"status": "ok"})

@app.route('/api/search')
def search():
    q = request.args.get('q', '')
    users = list(db.users.find({"username": {"$regex": q, "$options": "i"}}, {"password": 0}).limit(5))
    groups = list(db.groups.find({"title": {"$regex": q, "$options": "i"}}).limit(5))
    for x in users + groups: x['_id'] = str(x['_id'])
    return jsonify({"users": users, "groups": groups})

@app.route('/api/profile/save', methods=['POST'])
def save_profile():
    u = get_user()
    db.users.update_one({"_id": u['_id']}, {"$set": {"display_name": request.json['name'], "bio": request.json['bio']}})
    return jsonify({"status": "ok"})

@app.route('/api/groups/create', methods=['POST'])
def create_group():
    u = get_user()
    gid = db.groups.insert_one({"title": request.json['title'], "owner_id": str(u['_id']), "members": [str(u['_id'])], "admins": [str(u['_id'])]}).inserted_id
    return jsonify({"id": str(gid)})

@app.route('/api/my_chats')
def my_chats():
    u = get_user()
    gs = list(db.groups.find({"members": str(u['_id'])}))
    for g in gs: g['_id'] = str(g['_id'])
    return jsonify(gs)

@app.route('/api/upload', methods=['POST'])
def upload():
    f = request.files['file']
    return jsonify({"url": f"data:{f.content_type};base64,{base64.b64encode(f.read()).decode()}"})

# --- SOCKETS ---
@socketio.on('join_room')
def on_join(d): join_room(d['room'])

@socketio.on('send_msg')
def handle_msg(d):
    u = get_user()
    msg = {"room": d['room'], "sender_id": str(u['_id']), "sender_name": u['display_name'], "sender_avatar": u['avatar'], "text": d.get('text', ''), "type": d.get('type', 'text'), "file_url": d.get('file_url', ''), "ts": datetime.datetime.utcnow().isoformat()}
    msg['_id'] = str(db.messages.insert_one(msg).inserted_id)
    emit('new_message', msg, room=d['room'])
    emit('notify', d, room=d['room'], include_self=False)

@socketio.on('delete_msg')
def handle_del(d):
    db.messages.delete_one({"_id": ObjectId(d['msg_id'])})
    emit('msg_deleted', d['msg_id'], room=d['room'])

@socketio.on('call_user')
def call(d): emit('incoming_call', d, room=d['room'], include_self=False)
@socketio.on('answer_call')
def answer(d): emit('call_accepted', d, room=d['room'])
@socketio.on('ice_candidate')
def ice(d): emit('ice_candidate', d['candidate'], room=d['room'], include_self=False)
@socketio.on('hangup')
def hangup(d): emit('call_ended', room=d['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
