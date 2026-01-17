import eventlet
eventlet.monkey_patch()

import os
import time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pro-messenger-2026'
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=1000 * 1024 * 1024)

# ПОДКЛЮЧЕНИЕ К ТВОЕЙ БАЗЕ
MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URL)
db = client['messenger_db']

users_col = db['users']
rooms_col = db['rooms']
messages_col = db['messages']

# Создаем общий чат при первом запуске
if not rooms_col.find_one({"name": "Общий чат"}):
    rooms_col.insert_one({"name": "Общий чат", "type": "group", "owner": "system", "admins": [], "members": []})

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('login_attempt')
def handle_login(data):
    nick = data['nick']
    password = data['pass']
    name = data['name']
    
    user = users_col.find_one({"nick": nick})
    
    if user:
        if user['password'] == password:
            emit('login_success', {"name": user['name'], "nick": nick})
        else:
            emit('login_error', "Неверный пароль для этого @username")
    else:
        # Регистрация нового пользователя
        users_col.insert_one({"nick": nick, "password": password, "name": name})
        emit('login_success', {"name": name, "nick": nick})

@socketio.on('join')
def on_join(data):
    room_name = data['room']
    nick = data['nick']
    join_room(room_name)
    
    rooms_col.update_one({"name": room_name}, {"$addToSet": {"members": nick}})
    
    # Загрузка истории
    history = list(messages_col.find({"room": room_name}).sort("_id", -1).limit(50))
    formatted_history = []
    for m in history:
        formatted_history.append({"user": m['user'], "nick": m['nick'], "text": m['text']})
    
    emit('history', formatted_history[::-1])
    
    room_data = rooms_col.find_one({"name": room_name})
    if room_data:
        room_data['_id'] = str(room_data['_id'])
        emit('room_info', room_data, to=room_name)

@socketio.on('message')
def handle_message(data):
    messages_col.insert_one({
        "room": data['room'],
        "user": data['user'],
        "nick": data['nick'],
        "text": data['text'],
        "time": time.time()
    })
    emit('render_message', data, to=data['room'])

@socketio.on('create_room')
def create_room(data):
    if not rooms_col.find_one({"name": data['name']}):
        rooms_col.insert_one({
            "name": data['name'],
            "type": data['type'],
            "owner": data['user'],
            "admins": [],
            "members": [data['user']]
        })
        emit('room_created', {"name": data['name']}, broadcast=True)

@socketio.on('make_admin')
def make_admin(data):
    room = data['room']
    rooms_col.update_one({"name": room, "owner": data['requester']}, {"$addToSet": {"admins": data['target']}})
    updated = rooms_col.find_one({"name": room})
    updated['_id'] = str(updated['_id'])
    emit('room_info', updated, to=room)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
