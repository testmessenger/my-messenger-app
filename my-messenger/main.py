from gevent import monkey
monkey.patch_all()  # Должно быть строго первым!

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'litegram-pro-2026'
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100*1024*1024)

# Исправленное подключение к MongoDB (connect=False убирает KeyError)
MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URL, connect=False)
db = client['messenger_db']
users_col = db['users']
messages_col = db['messages']
rooms_col = db['rooms']

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
        else: emit('login_error', "Неверный пароль")
    else:
        new_user = {"nick": nick, "password": data['pass'], "name": data['name'], "avatar": ""}
        users_col.insert_one(new_user)
        emit('login_success', {"name": data['name'], "nick": nick, "avatar": ""})

@socketio.on('search')
def handle_search(data):
    q = data['query'].lower()
    users = list(users_col.find({"nick": {"$regex": q}}, {"_id":0, "password":0}))
    rooms = list(rooms_col.find({"name": {"$regex": q}}, {"_id":0}))
    emit('search_results', {"users": users, "rooms": rooms})

@socketio.on('get_my_rooms')
def get_rooms():
    rooms = list(rooms_col.find({}, {"_id": 0}))
    emit('load_rooms', rooms)

@socketio.on('create_room')
def create_room(data):
    # creator становится владельцем и первым админом
    data['admins'] = [data['creator']] 
    rooms_col.update_one({"id": data['id']}, {"$set": data}, upsert=True)
    emit('room_created', data, broadcast=True)

@socketio.on('delete_room_global')
def delete_room(data):
    room = rooms_col.find_one({"id": data['room']})
    if room and room['creator'] == data['nick']:
        rooms_col.delete_one({"id": data['room']})
        messages_col.delete_many({"room": data['room']})
        emit('room_deleted_event', data['room'], broadcast=True)

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)
    history = list(messages_col.find({"room": room}).sort("_id", -1).limit(50))
    for m in history: m['_id'] = str(m['_id'])
    emit('history', history[::-1])

@socketio.on('message')
def handle_message(data):
    data['time'] = time.time()
    res = messages_col.insert_one(data.copy())
    data['_id'] = str(res.inserted_id)
    emit('render_message', data, to=data['room'])

@socketio.on('add_reaction')
def add_reaction(data):
    msg_id = data['msg_id']
    emoji = data['emoji']
    nick = data['nick']
    msg = messages_col.find_one({"_id": ObjectId(msg_id)})
    if msg:
        reactions = msg.get('reactions', {})
        if emoji not in reactions: reactions[emoji] = []
        if nick in reactions[emoji]: reactions[emoji].remove(nick)
        else: reactions[emoji].append(nick)
        messages_col.update_one({"_id": ObjectId(msg_id)}, {"$set": {"reactions": reactions}})
        emit('update_reactions', {"msg_id": msg_id, "reactions": reactions}, room=data['room'])

@socketio.on('delete_msg')
def delete_msg(data):
    # Проверка прав: автор сообщения ИЛИ админ комнаты может удалять
    msg = messages_col.find_one({"_id": ObjectId(data['msg_id'])})
    room = rooms_col.find_one({"id": data['room']})
    is_admin = room and data['nick'] in room.get('admins', [])
    if msg and (msg['nick'] == "@"+data['nick'] or is_admin):
        messages_col.delete_one({"_id": ObjectId(data['msg_id'])})
        emit('msg_deleted_confirm', {"msg_id": data['msg_id']}, room=data['room'])

@socketio.on('update_avatar')
def update_avatar(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"avatar": data['avatar']}})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
