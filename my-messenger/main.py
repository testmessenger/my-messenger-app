import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import datetime, os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NEXUS_ULTIMATE_2026'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

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
def index():
    u = get_u()
    return render_template('index.html', user=fix(u)) if u else redirect('/auth')

@app.route('/auth')
def auth_p(): return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def handle_auth():
    d = request.json
    if d.get('reg'):
        if db.users.find_one({"username": d['username']}): return jsonify({"e": "Занято"}), 400
        uid = db.users.insert_one({"username": d['username'], "pw": generate_password_hash(d['pw']), "name": d['username'], "av": "/static/default.png", "bio": "Nexus User", "theme": "dark", "last_seen": ""}).inserted_id
        session['user_id'] = str(uid)
    else:
        u = db.users.find_one({"username": d['username']})
        if u and check_password_hash(u['pw'], d['pw']): session['user_id'] = str(u['_id'])
        else: return jsonify({"e": "Ошибка"}), 401
    return jsonify({"s": "ok"})

@app.route('/api/upload', methods=['POST'])
def upload():
    u = get_u()
    f = request.files.get('file')
    if f:
        fname = secure_filename(f"{u['username']}_{f.filename}")
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        url = f"/static/uploads/{fname}"
        if request.form.get('type') == 'avatar': db.users.update_one({"_id": u['_id']}, {"$set": {"av": url}})
        return jsonify({"url": url})
    return "Error", 400

@app.route('/api/groups', methods=['GET', 'POST'])
def groups():
    u = get_u()
    if request.method == 'POST':
        db.groups.insert_one({"title": request.json['t'], "owner": str(u['_id']), "admins": [str(u['_id'])], "members": [str(u['_id'])], "muted": [], "banned": []})
        return "ok"
    gs = list(db.groups.find({"members": str(u['_id'])}))
    for g in gs: 
        g['m_count'] = len(g['members'])
        g['member_details'] = fix(list(db.users.find({"_id": {"$in": [ObjectId(m) for m in g['members']]}}, {"pw":0})))
    return jsonify(fix(gs))

@socketio.on('join')
def on_join(d): join_room(d['room'])

@socketio.on('typing')
def on_typing(d):
    u = get_u()
    emit('is_typing', {"name": u['name'], "room": d['room'], "st": d['st'], "is_g": d['is_g']}, room=d['room'], include_self=False)

@socketio.on('msg')
def on_msg(d):
    u = get_u()
    m = {"room": d['room'], "sid": str(u['_id']), "name": u['name'], "av": u['av'], "txt": d.get('txt'), 
         "type": d.get('type', 'text'), "url": d.get('url'), "reactions": {}, "ts": datetime.datetime.utcnow().isoformat()}
    m['_id'] = str(db.messages.insert_one(m).inserted_id)
    emit('new_msg', m, room=d['room'])

@socketio.on('reaction')
def on_react(d):
    db.messages.update_one({"_id": ObjectId(d['mid'])}, {"$inc": {f"reactions.{d['emoji']}": 1}})
    emit('update_reactions', d, room=d['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
