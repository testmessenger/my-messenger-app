from gevent import monkey
monkey.patch_all()
import os, flask, flask_socketio, pymongo

app = flask.Flask(__name__)
socketio = flask_socketio.SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100*1024*1024)
db = pymongo.MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true", connect=False)['messenger_db']

@app.route('/')
def index(): return flask.render_template('index.html')

@socketio.on('auth')
def auth(data):
    nick = data['nick'].replace('@','').lower().strip()
    u = db.users.find_one({"nick": nick})
    if data['type'] == 'reg':
        if u: return socketio.emit('auth_err', "Ник занят")
        u = {"nick": nick, "password": data['pass'], "name": nick, "avatar": "", "bio": "О себе...", "theme": "dark-theme"}
        db.users.insert_one(u)
    else:
        if not u or u['password'] != data['pass']: return socketio.emit('auth_err', "Ошибка входа")
    u.pop('_id'); socketio.emit('auth_ok', u)

@socketio.on('update_profile')
def up_prof(data):
    db.users.update_one({"nick": data['nick']}, {"$set": {"name": data['name'], "avatar": data['avatar'], "bio": data['bio'], "theme": data['theme']}})
    socketio.emit('auth_ok', db.users.find_one({"nick": data['nick']}, {"_id":0}))

@socketio.on('message')
def handle_msg(data):
    r = db.rooms.find_one({"id": data['room']})
    if r and data['nick'] in r.get('muted', []): return
    data['id'], data['reactions'] = os.urandom(4).hex(), {}
    db.messages.insert_one(data.copy())
    data.pop('_id', None)
    socketio.emit('render_message', data, to=data['room'])

@socketio.on('admin_action')
def admin_act(data):
    r = db.rooms.find_one({"id": data['room']})
    if not r or (data['nick'] != r['owner'] and data['nick'] not in r.get('admins', [])): return
    t, a = data['target'], data['action']
    if a == 'ban': db.rooms.update_one({"id": data['room']}, {"$pull": {"members": t}, "$push": {"banned": t}})
    elif a == 'mute': db.rooms.update_one({"id": data['room']}, {"$addToSet": {"muted": t}})
    elif a == 'promote' and data['nick'] == r['owner']: db.rooms.update_one({"id": data['room']}, {"$addToSet": {"admins": t}})
    socketio.emit('room_update', db.rooms.find_one({"id": data['room']}, {"_id":0}), to=data['room'])

@socketio.on('delete_chat')
def del_chat(data):
    r = db.rooms.find_one({"id": data['room']})
    if r and r['owner'] == data['nick']:
        db.rooms.delete_one({"id": data['room']}); db.messages.delete_many({"room": data['room']})
        socketio.emit('chat_gone', data['room'])

@socketio.on('create_room')
def cr_room(data):
    rid = "group_"+os.urandom(3).hex()
    db.rooms.insert_one({"id":rid,"name":data['name'],"owner":data['nick'],"members":[data['nick']],"admins":[],"muted":[],"banned":[],"type":"group"})
    socketio.emit('load_rooms', list(db.rooms.find({"members": data['nick']}, {"_id":0})))

@socketio.on('join')
def on_join(data):
    r = db.rooms.find_one({"id": data['room']})
    if r and data['nick'] in r.get('banned', []): return
    flask_socketio.join_room(data['room'])
    socketio.emit('room_update', r)
    h = list(db.messages.find({"room":data['room']}).sort("_id",-1).limit(50))
    for m in h: m.pop('_id', None)
    socketio.emit('history', h[::-1])

@socketio.on('get_user')
def get_user(n):
    u = db.users.find_one({"nick": n.replace('@','')}, {"_id":0, "password":0})
    if u: socketio.emit('user_info', u)

@socketio.on('add_reaction')
def add_react(data):
    db.messages.update_one({"id": data['msg_id']}, {"$set": {f"reactions.{data['nick']}": data['emoji']}})
    m = db.messages.find_one({"id": data['msg_id']}, {"_id":0})
    socketio.emit('update_msg', m, to=data['room'])

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
