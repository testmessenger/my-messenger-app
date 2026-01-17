from gevent import monkey
monkey.patch_all()
import os, flask, flask_socketio, pymongo

app = flask.Flask(__name__)
socketio = flask_socketio.SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100*1024*1024)

db = pymongo.MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true", connect=False)['messenger_db']

@app.route('/')
def index(): return flask.render_template('index.html')

@socketio.on('login_attempt')
def login(data):
    nick = data['nick'].replace('@','').lower().strip()
    u = db.users.find_one({"nick": nick})
    if not u: db.users.insert_one({"nick": nick, "password": data['pass'], "name": nick})
    elif u['password'] != data['pass']: return emit('login_error', "Ошибка")
    flask_socketio.emit('login_success', {"nick": nick})

@socketio.on('message')
def handle_msg(data):
    r = db.rooms.find_one({"id": data['room']})
    if r and data['nick'] in r.get('muted', []): return
    data['id'] = os.urandom(4).hex()
    db.messages.insert_one(data.copy())
    data.pop('_id', None)
    socketio.emit('render_message', data, to=data['room'])

@socketio.on('admin_action')
def admin_act(data):
    room = db.rooms.find_one({"id": data['room']})
    if not room: return
    is_mod = (data['nick'] == room.get('owner')) or (data['nick'] in room.get('admins', []))
    if is_mod:
        if data['action'] == 'ban':
            db.rooms.update_one({"id": data['room']}, {"$pull": {"members": data['target']}, "$push": {"banned": data['target']}})
            socketio.emit('kick_user', data['target'], to=data['room'])
        elif data['action'] == 'mute':
            db.rooms.update_one({"id": data['room']}, {"$addToSet": {"muted": data['target']}})
        elif data['action'] == 'promote' and data['nick'] == room['owner']:
            db.rooms.update_one({"id": data['room']}, {"$addToSet": {"admins": data['target']}})
    socketio.emit('room_update', db.rooms.find_one({"id": data['room']}, {"_id":0}), to=data['room'])

@socketio.on('delete_message')
def del_msg(data):
    db.messages.delete_one({"id": data['msg_id']})
    socketio.emit('remove_msg', data['msg_id'], to=data['room'])

@socketio.on('delete_chat')
def del_chat(data):
    room = db.rooms.find_one({"id": data['room']})
    if room and room['owner'] == data['nick']:
        db.messages.delete_many({"room": data['room']})
        db.rooms.delete_one({"id": data['room']})
        socketio.emit('chat_gone', data['room'])

@socketio.on('create_room')
def cr_room(data):
    rid = "group_"+os.urandom(3).hex()
    db.rooms.insert_one({"id":rid, "name":data['name'], "owner":data['nick'], "members":[data['nick']], "admins":[], "muted":[], "banned":[]})
    socketio.emit('load_rooms', list(db.rooms.find({"members": data['nick']}, {"_id":0})))

@socketio.on('join')
def on_join(data):
    flask_socketio.join_room(data['room'])
    h = list(db.messages.find({"room":data['room']}).sort("_id",-1).limit(40))
    for m in h: m.pop('_id', None)
    flask_socketio.emit('history', h[::-1])
    flask_socketio.emit('room_update', db.rooms.find_one({"id": data['room']}, {"_id":0}))

@socketio.on('get_rooms')
def g_rooms(data): flask_socketio.emit('load_rooms', list(db.rooms.find({"members": data['nick']}, {"_id":0})))

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
