from gevent import monkey
monkey.patch_all()
import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024)

MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URL, connect=False)
db = client['messenger_db']
users_col, messages_col, rooms_col = db['users'], db['messages'], db['rooms']

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('login_attempt')
def login(data):
    nick = data['nick'].replace('@', '').lower().strip()
    user = users_col.find_one({"nick": nick})
    if user:
        if user['password'] == data['pass']:
            emit('login_success', {"name": user['name'], "nick": nick, "avatar": user.get('avatar', ''), "bio": user.get('bio', '')})
        else: emit('login_error', "Ошибка пароля")
    else:
        new_u = {"nick": nick, "password": data['pass'], "name": nick, "avatar": "", "bio": "", "rank": "Участник"}
        users_col.insert_one(new_u)
        emit('login_success', {"name": nick, "nick": nick, "avatar": "", "bio": ""})

@socketio.on('create_room')
def create_room(data):
    room_id = "group_" + str(os.urandom(4).hex())
    new_room = {"id": room_id, "name": data['name'], "members": [data['creator_nick']], "type": "group"}
    rooms_col.insert_one(new_room)
    rooms = list(rooms_col.find({"members": data['creator_nick']}, {"_id": 0}))
    emit('load_rooms', rooms)

@socketio.on('get_my_rooms')
def get_rooms(data):
    rooms = list(rooms_col.find({"members": data['nick']}, {"_id": 0}))
    emit('load_rooms', rooms)

@socketio.on('message')
def handle_msg(data):
    data['id'] = str(os.urandom(4).hex())
    messages_col.insert_one(data.copy())
    data.pop('_id', None)
    emit('render_message', data, to=data['room'])

@socketio.on('typing')
def handle_typing(data):
    emit('display_typing', data, to=data['room'], include_self=False)

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    h = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(50))
    for m in h: m.pop('_id', None)
    emit('history', h[::-1])

@socketio.on('get_members')
def get_members(data):
    m_list = list(users_col.find({}, {"_id":0, "password":0}).limit(100))
    emit('members_list', m_list)

@socketio.on('get_user_info')
def get_info(data):
    u = users_col.find_one({"nick": data['nick']}, {"_id":0, "password":0})
    if u: emit('user_info_res', u)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
