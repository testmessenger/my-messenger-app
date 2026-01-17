import eventlet
eventlet.monkey_patch()

import os
import time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pro-messenger-2026-secure'
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=1000 * 1024 * 1024)

# ПОДКЛЮЧЕНИЕ К БАЗЕ
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
    rooms_col.update_one({"name": room_name}, {"$addToSet": {"members": nick}})
    
    # Загрузка истории (превращаем ObjectId в строку для JS)
    history = list(messages_col.find({"room": room_name}).sort("_id", -1).limit(50))
    for m in history:
        m['_id'] = str(m['_id'])
    
    emit('history', history[::-1])
    
    room_data = rooms_col.find_one({"name": room_name})
    if room_data:
        room_data['_id'] = str(room_data['_id'])
        emit('room_info', room_data, to=room_name)

@socketio.on('message')
def handle_message(data):
    # Сохраняем и получаем ID
    msg_obj = {
        "room": data['room'],
        "user": data['user'],
        "nick": data['nick'],
        "text": data['text'],
        "time": time.time()
    }
    result = messages_col.insert_one(msg_obj)
    data['_id'] = str(result.inserted_id)
    emit('render_message', data, to=data['room'])

@socketio.on('edit_message')
def edit_message(data):
    msg_id = data['msg_id']
    new_text = data['new_text']
    messages_col.update_one({"_id": ObjectId(msg_id)}, {"$set": {"text": new_text}})
    emit('message_edited', {"msg_id": msg_id, "new_text": new_text}, to=data['room'])

@socketio.on('delete_message')
def delete_message(data):
    messages_col.delete_one({"_id": ObjectId(data['msg_id'])})
    emit('message_deleted', {"msg_id": data['msg_id']}, to=data['room'])

@socketio.on('delete_chat')
def delete_chat(data):
    room = rooms_col.find_one({"name": data['room']})
    if room and room['owner'] == data['requester']:
        rooms_col.delete_one({"name": data['room']})
        messages_col.delete_many({"room": data['room']})
        emit('chat_deleted', {"room": data['room']}, broadcast=True)

@socketio.on('create_room')
def create_room(data):
    if not rooms_col.find_one({"name": data['name']}):
        rooms_col.insert_one({
            "name": data['name'], "type": "group", 
            "owner": data['user'], "admins": [], "members": [data['user']]
        })
        emit('room_created', {"name": data['name']}, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
