from gevent import monkey
monkey.patch_all()

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'litegram-ultra-elite'
# Поддержка больших файлов (для длинных голосовых)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100 * 1024 * 1024)

# Подключение к MongoDB
MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URL)
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
        else: emit('login_error', "Ошибка!")
    else:
        new_user = {"nick": nick, "password": data['pass'], "name": data['name'], "avatar": ""}
        users_col.insert_one(new_user)
        emit('login_success', {"name": data['name'], "nick": nick, "avatar": ""})

@socketio.on('get_my_rooms')
def get_rooms():
    rooms = list(rooms_col.find({}, {"_id": 0}))
    emit('load_rooms', rooms)

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
    data['reactions'] = {}
    res = messages_col.insert_one(data.copy())
    data['_id'] = str(res.inserted_id)
    emit('render_message', data, to=data['room'])

@socketio.on('create_room')
def create_room(data):
    rooms_col.update_one({"id": data['id']}, {"$set": data}, upsert=True)
    emit('room_created', data, broadcast=True)

@socketio.on('add_reaction')
def add_reaction(data):
    msg_id = data['msg_id']
    emoji = data['emoji']
    nick = data['nick']
    msg = messages_col.find_one({"_id": ObjectId(msg_id)})
    if msg:
        reactions = msg.get('reactions', {})
        if emoji not in reactions: reactions[emoji] = []
        if nick in reactions[emoji]:
            reactions[emoji].remove(nick)
            if not reactions[emoji]: del reactions[emoji]
        else: reactions[emoji].append(nick)
        messages_col.update_one({"_id": ObjectId(msg_id)}, {"$set": {"reactions": reactions}})
        emit('update_reactions', {"msg_id": msg_id, "reactions": reactions}, room=data['room'])

@socketio.on('delete_msg_global')
def delete_msg(data):
    messages_col.delete_one({"_id": ObjectId(data['msg_id'])})
    emit('msg_deleted_confirm', {"msg_id": data['msg_id']}, room=data['room'])

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', data, room=data['room'], include_self=False)

@socketio.on('update_avatar')
def update_avatar(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"avatar": data['avatar']}})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
