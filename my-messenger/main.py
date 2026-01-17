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
        u = {"nick": nick, "password": data['pass'], "name": nick, "avatar": "", "bio": "", "theme": "dark"}
        db.users.insert_one(u)
    else:
        if not u or u['password'] != data['pass']: return socketio.emit('auth_err', "Ошибка входа")
    u.pop('_id'); socketio.emit('auth_ok', u)

@socketio.on('get_user')
def get_user(nick):
    u = db.users.find_one({"nick": nick.replace('@','').lower()}, {"_id":0, "password":0})
    if u: socketio.emit('user_info', u)

@socketio.on('update_profile')
def up_prof(data):
    db.users.update_one({"nick": data['nick']}, {"$set": {
        "name": data['name'], "avatar": data['avatar'], "bio": data['bio'], "theme": data['theme']
    }})
    socketio.emit('auth_ok', db.users.find_one({"nick":data['nick']},{"_id":0}))

@socketio.on('message')
def handle_msg(data):
    data['id'] = os.urandom(4).hex()
    db.messages.insert_one(data.copy())
    data.pop('_id', None)
    socketio.emit('render_message', data, to=data['room'])

@socketio.on('create_room')
def cr_room(data):
    rid = "group_"+os.urandom(3).hex()
    db.rooms.insert_one({"id":rid, "name":data['name'], "owner":data['nick'], "members":[data['nick']], "type":"group"})
    socketio.emit('load_rooms', list(db.rooms.find({"members": data['nick']}, {"_id":0})))

@socketio.on('join')
def on_join(data):
    flask_socketio.join_room(data['room'])
    socketio.emit('room_info', db.rooms.find_one({"id": data['room']}, {"_id":0}))
    h = list(db.messages.find({"room":data['room']}).sort("_id",-1).limit(40))
    for m in h: m.pop('_id', None)
    socketio.emit('history', h[::-1])

@socketio.on('get_rooms')
def g_rooms(n): socketio.emit('load_rooms', list(db.rooms.find({"members": n}, {"_id":0})))

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000)
