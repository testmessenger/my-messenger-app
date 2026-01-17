from gevent import monkey
monkey.patch_all()

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ultra-litegram-2026'
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100 * 1024 * 1024)

# Подключение к MongoDB
MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URL)
db = client['messenger_db']
users_col = db['users']
messages_col = db['messages']
rooms_col = db['rooms'] # Коллекция для групп и каналов

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('login_attempt')
def handle_login(data):
    nick = data['nick'].replace('@', '').lower()
    user = users_col.find_one({"nick": nick})
    if user:
        if user['password'] == data['pass']:
            emit('login_success', {"name": user['name'], "nick": nick, "avatar": user.get('avatar', '')})
        else: emit('login_error', "Неверный пароль!")
    else:
        new_user = {"nick": nick, "password": data['pass'], "name": data['name'], "avatar": "", "last_seen": time.time()}
        users_col.insert_one(new_user)
        emit('login_success', {"name": data['name'], "nick": nick, "avatar": ""})

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)
    # Загружаем историю конкретной комнаты
    history = list(messages_col.find({"room": room}).sort("_id", -1).limit(50))
    for m in history: m['_id'] = str(m['_id'])
    emit('history', history[::-1])

@socketio.on('message')
def handle_message(data):
    data['time'] = time.time()
    user = users_col.find_one({"nick": data['nick'].replace('@','')})
    data['avatar'] = user.get('avatar', '') if user else ''
    res = messages_col.insert_one(data.copy())
    data['_id'] = str(res.inserted_id)
    emit('render_message', data, to=data['room'])

@socketio.on('create_room')
def create_room(data):
    # data = {name, type, creator}
    room_id = data['name'].lower().replace(' ', '_')
    rooms_col.update_one({"id": room_id}, {"$set": data}, upsert=True)
    emit('room_created', data, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', data, room=data['room'], include_self=False)

@socketio.on('update_avatar')
def update_avatar(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"avatar": data['avatar']}})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
