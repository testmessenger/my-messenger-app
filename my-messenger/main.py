from gevent import monkey
monkey.patch_all()
import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100 * 1024 * 1024)

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
            emit('login_success', {"name": user.get('name', nick), "nick": nick})
        else: emit('login_error', "Ошибка")
    else:
        new_u = {"nick": nick, "password": data['pass'], "name": nick}
        users_col.insert_one(new_u)
        emit('login_success', {"name": nick, "nick": nick})

@socketio.on('message')
def handle_msg(data):
    room = rooms_col.find_one({"id": data['room']})
    if room and data['nick'] in room.get('muted', []):
        return # Пользователь в муте
    data['id'] = str(os.urandom(6).hex())
    data['reactions'] = {}
    messages_col.insert_one(data.copy())
    data.pop('_id', None)
    emit('render_message', data, to=data['room'])

@socketio.on('admin_action')
def admin_action(data):
    room_id = data['room']
    target = data['target']
    action = data['action'] # ban, mute, promote
    nick = data['nick'] # кто делает

    room = rooms_col.find_one({"id": room_id})
    if not room: return
    
    is_owner = room.get('owner') == nick
    is_admin = nick in room.get('admins', [])
    
    if is_owner or is_admin:
        if action == 'ban':
            rooms_col.update_one({"id": room_id}, {"$pull": {"members": target}, "$push": {"banned": target}})
            emit('user_banned', {"room": room_id, "target": target}, broadcast=True)
        elif action == 'mute':
            rooms_col.update_one({"id": room_id}, {"$addToSet": {"muted": target}})
            emit('user_muted', {"room": room_id, "target": target}, broadcast=True)
        elif action == 'promote' and is_owner:
            rooms_col.update_one({"id": room_id}, {"$addToSet": {"admins": target}})
    
    # Обновляем инфо о комнате у всех
    updated_room = rooms_col.find_one({"id": room_id}, {"_id": 0})
    emit('room_update', updated_room, to=room_id)

@socketio.on('delete_message')
def delete_msg(data):
    msg = messages_col.find_one({"id": data['msg_id']})
    if msg and (msg['nick'] == data['nick']): # Только автор в этой версии
        messages_col.delete_one({"id": data['msg_id']})
        emit('remove_message_from_ui', data['msg_id'], to=data['room'])

@socketio.on('create_room')
def create_room(data):
    room_id = "group_" + str(os.urandom(4).hex())
    new_room = {
        "id": room_id, "name": data['name'], "owner": data['creator_nick'],
        "members": [data['creator_nick']], "admins": [], "banned": [], "muted": [], "type": "group"
    }
    rooms_col.insert_one(new_room)
    emit('load_rooms', list(rooms_col.find({"members": data['creator_nick']}, {"_id": 0})))

@socketio.on('join')
def on_join(data):
    room = rooms_col.find_one({"id": data['room']})
    if room and data['nick'] in room.get('banned', []):
        emit('error', "Вы забанены в этом чате")
        return
    join_room(data['room'])
    h = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(50))
    for m in h: m.pop('_id', None)
    emit('history', h[::-1])
    emit('room_update', rooms_col.find_one({"id": data['room']}, {"_id": 0}))

@socketio.on('get_my_rooms')
def get_rooms(data):
    emit('load_rooms', list(rooms_col.find({"members": data['nick']}, {"_id": 0})))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
