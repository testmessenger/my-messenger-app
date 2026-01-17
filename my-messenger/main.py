import eventlet
eventlet.monkey_patch()

import os
import time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secure-key-2026'
# Увеличиваем лимит для передачи картинок (до 20МБ)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=20 * 1024 * 1024)

MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URL)
db = client['messenger_db']

users_col = db['users']
rooms_col = db['rooms']
messages_col = db['messages']

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('login_attempt')
def handle_login(data):
    nick = data['nick'].replace('@', '').lower()
    user = users_col.find_one({"nick": nick})
    if user:
        if user['password'] == data['pass']:
            emit('login_success', {"name": user['name'], "nick": nick})
        else:
            emit('login_error', "Неверный пароль!")
    else:
        users_col.insert_one({"nick": nick, "password": data['pass'], "name": data['name']})
        emit('login_success', {"name": data['name'], "nick": nick})

@socketio.on('join')
def on_join(data):
    room_name = data['room']
    nick = data['nick']
    join_room(room_name)
    
    # Загрузка истории
    history = list(messages_col.find({"room": room_name}).sort("_id", -1).limit(50))
    for m in history: m['_id'] = str(m['_id'])
    emit('history', history[::-1])
    
    # Если это группа, обновляем инфо
    room_data = rooms_col.find_one({"name": room_name})
    if room_data:
        room_data['_id'] = str(room_data['_id'])
        emit('room_info', room_data, to=room_name)

@socketio.on('message')
def handle_message(data):
    # data может содержать 'file' и 'file_type'
    msg_obj = {
        "room": data['room'],
        "user": data['user'],
        "nick": data['nick'],
        "text": data.get('text', ''),
        "file": data.get('file'), 
        "file_type": data.get('file_type'),
        "time": time.time()
    }
    result = messages_col.insert_one(msg_obj)
    data['_id'] = str(result.inserted_id)
    emit('render_message', data, to=data['room'])

@socketio.on('search_user')
def search_user(data):
    query = data['query'].replace('@', '').lower()
    user = users_col.find_one({"nick": query})
    if user:
        emit('user_found', {"nick": user['nick'], "name": user['name']})
    else:
        emit('login_error', "Пользователь не найден")

@socketio.on('edit_message')
def edit_message(data):
    messages_col.update_one({"_id": ObjectId(data['msg_id'])}, {"$set": {"text": data['new_text']}})
    emit('message_edited', data, to=data['room'])

@socketio.on('delete_message')
def delete_message(data):
    messages_col.delete_one({"_id": ObjectId(data['msg_id'])})
    emit('message_deleted', data, to=data['room'])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
