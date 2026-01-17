from gevent import monkey
monkey.patch_all()

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=20 * 1024 * 1024)

# Подключение к MongoDB
MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URL, connect=False)
db = client['messenger_db']
users_col, messages_col, rooms_col = db['users'], db['messages'], db['rooms']

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('login_attempt')
def login(data):
    nick = data['nick'].replace('@', '').lower().strip()
    password = data['pass'].strip()
    name = data.get('name') or nick
    
    if not nick or not password:
        emit('login_error', "Заполните все поля!")
        return

    user = users_col.find_one({"nick": nick})
    if user:
        if user['password'] == password:
            emit('login_success', {"name": user['name'], "nick": nick, "avatar": user.get('avatar', '')})
        else:
            emit('login_error', "Неверный пароль!")
    else:
        users_col.insert_one({"nick": nick, "password": password, "name": name, "avatar": ""})
        emit('login_success', {"name": name, "nick": nick, "avatar": ""})

@socketio.on('get_rooms')
def get_rooms():
    # Отдаем все существующие комнаты (группы/каналы)
    rooms = list(rooms_col.find({}, {"_id": 0}))
    emit('load_rooms', rooms)

@socketio.on('create_room')
def create_r(data):
    if not rooms_col.find_one({"id": data['id']}):
        rooms_col.insert_one(data)
        emit('room_created', data, broadcast=True)

@socketio.on('search')
def search(data):
    q = data['query'].lower().strip()
    if not q: return
    users = list(users_col.find({"nick": {"$regex": q}}, {"_id":0, "password":0}))
    rooms = list(rooms_col.find({"name": {"$regex": q, "$options": "i"}}, {"_id":0}))
    emit('search_results', {"users": users, "rooms": rooms})

@socketio.on('message')
def handle_msg(data):
    messages_col.insert_one(data)
    emit('render_message', data, to=data['room'])

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    h = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(50))
    emit('history', [ {k:v for k,v in m.items() if k != '_id'} for m in h[::-1] ])

@socketio.on('update_profile_image')
def update_img(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"avatar": data['img']}})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
