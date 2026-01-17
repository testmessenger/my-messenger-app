from gevent import monkey
monkey.patch_all()
import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100 * 1024 * 1024)

# Подключение к БД
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
        new_u = {"nick": nick, "password": data['pass'], "name": nick, "avatar": "", "bio": ""}
        users_col.insert_one(new_u)
        emit('login_success', {"name": nick, "nick": nick, "avatar": "", "bio": ""})

@socketio.on('message')
def handle_msg(data):
    data['id'] = str(os.urandom(6).hex())
    data['reactions'] = {}
    messages_col.insert_one(data.copy())
    data.pop('_id', None)
    emit('render_message', data, to=data['room'])

@socketio.on('delete_message')
def delete_msg(data):
    # data: {msg_id, room, nick}
    # Проверяем, что удаляет автор (базовая защита)
    msg = messages_col.find_one({"id": data['msg_id']})
    if msg and msg['nick'] == data['nick']:
        messages_col.delete_one({"id": data['msg_id']})
        emit('remove_message_from_ui', data['msg_id'], to=data['room'])

@socketio.on('add_reaction')
def add_reaction(data):
    messages_col.update_one({"id": data['msg_id']}, {"$set": {f"reactions.{data['nick']}": data['emoji']}})
    msg = messages_col.find_one({"id": data['msg_id']}, {"_id": 0})
    emit('update_reactions', msg, to=data['room'])

@socketio.on('create_room')
def create_room(data):
    room_id = "group_" + str(os.urandom(4).hex())
    rooms_col.insert_one({"id": room_id, "name": data['name'], "members": [data['creator_nick']], "type": "group"})
    emit('load_rooms', list(rooms_col.find({"members": data['creator_nick']}, {"_id": 0})))

@socketio.on('get_my_rooms')
def get_rooms(data):
    emit('load_rooms', list(rooms_col.find({"members": data['nick']}, {"_id": 0})))

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    h = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(50))
    for m in h: m.pop('_id', None)
    emit('history', h[::-1])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
