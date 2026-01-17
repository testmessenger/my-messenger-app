from gevent import monkey
monkey.patch_all()

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
# Поддержка больших данных (голосовые)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100*1024*1024)

# Подключение к базе (connect=False убирает KeyError)
MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URL, connect=False)
db = client['messenger_db']
users_col, messages_col, rooms_col = db['users'], db['messages'], db['rooms']

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('login_attempt')
def login(data):
    nick = data['nick'].replace('@', '').lower()
    user = users_col.find_one({"nick": nick})
    if user and user['password'] == data['pass']:
        emit('login_success', {"name": user['name'], "nick": nick, "avatar": user.get('avatar', '')})
    elif not user:
        users_col.insert_one({"nick": nick, "password": data['pass'], "name": data['name'], "avatar": ""})
        emit('login_success', {"name": data['name'], "nick": nick, "avatar": ""})
    else: emit('login_error', "Ошибка!")

@socketio.on('message')
def handle_msg(data):
    data['time'] = time.time()
    res = messages_col.insert_one(data.copy())
    data['_id'] = str(res.inserted_id)
    emit('render_message', data, to=data['room'])

# СИГНАЛЫ ДЛЯ ЗВОНКОВ
@socketio.on('call_user')
def handle_call(data):
    emit('calling', data, room=data['room'], include_self=False)

@socketio.on('answer_call')
def handle_answer(data):
    emit('call_accepted', data, room=data['room'], include_self=False)

@socketio.on('ice_candidate')
def handle_ice(data):
    emit('remote_ice', data, room=data['room'], include_self=False)

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    h = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(50))
    for m in h: m['_id'] = str(m['_id'])
    emit('history', h[::-1])

@socketio.on('get_my_rooms')
def get_rooms():
    emit('load_rooms', list(rooms_col.find({}, {"_id": 0})))

@socketio.on('create_room')
def create_r(data):
    data['admins'] = [data['creator']]
    rooms_col.update_one({"id": data['id']}, {"$set": data}, upsert=True)
    emit('room_created', data, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
