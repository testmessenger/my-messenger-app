from gevent import monkey
monkey.patch_all()

import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024)

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
        if user.get('banned'): return emit('login_error', "Вы забанены!")
        if user['password'] == data['pass']:
            emit('login_success', {"name": user['name'], "nick": nick, "avatar": user.get('avatar', ''), "rank": user.get('rank', 'Участник'), "bio": user.get('bio', '')})
        else: emit('login_error', "Неверный пароль!")
    else:
        rank = "Админ" if users_col.count_documents({}) == 0 else "Участник"
        new_u = {"nick": nick, "password": data['pass'], "name": data.get('name') or nick, "avatar": "", "rank": rank, "bio": "", "banned": False}
        users_col.insert_one(new_u)
        emit('login_success', {"name": new_u['name'], "nick": nick, "avatar": "", "rank": rank, "bio": ""})

@socketio.on('get_my_rooms')
def get_my_rooms(data):
    nick = data['nick']
    # Показываем комнаты, где пользователь в списке members
    my_rooms = list(rooms_col.find({"members": nick}, {"_id": 0}))
    emit('load_rooms', my_rooms)

@socketio.on('search')
def search(data):
    q = data['query'].lower().strip()
    if not q: return
    users = list(users_col.find({"nick": {"$regex": q}}, {"_id":0, "password":0}))
    rooms = list(rooms_col.find({"name": {"$regex": q, "$options": "i"}}, {"_id":0}))
    emit('search_results', {"users": users, "rooms": rooms})

@socketio.on('join_room_request')
def join_r(data):
    rooms_col.update_one({"id": data['room_id']}, {"$addToSet": {"members": data['nick']}})
    emit('load_rooms_trigger')

@socketio.on('create_room')
def create_r(data):
    data['members'] = [data['creator']]
    rooms_col.insert_one(data)
    emit('room_created', data)

@socketio.on('message')
def handle_msg(data):
    user = users_col.find_one({"nick": data['nick']})
    if user and not user.get('banned'):
        data['rank'] = user.get('rank', 'Участник')
        messages_col.insert_one(data.copy())
        data.pop('_id', None)
        emit('render_message', data, to=data['room'])

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    h = [ {k:v for k,v in m.items() if k != '_id'} for m in messages_col.find({"room": data['room']}).sort("_id", -1).limit(50) ]
    emit('history', h[::-1])

@socketio.on('get_members')
def get_members(data=None): # data=None исправляет твою ошибку!
    if not data or 'room' not in data:
        # Если комната не указана, просто шлем список всех для ЛС
        m_list = list(users_col.find({"banned": {"$ne": True}}, {"_id":0, "password":0}).limit(30))
    else:
        room = rooms_col.find_one({"id": data['room']})
        if room and 'members' in room:
            m_list = list(users_col.find({"nick": {"$in": room['members']}}, {"_id":0, "password":0}))
        else:
            m_list = list(users_col.find({"banned": {"$ne": True}}, {"_id":0, "password":0}).limit(30))
    emit('members_list', m_list)

@socketio.on('update_profile')
def update_profile(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"name": data['name'], "bio": data['bio'], "avatar": data['avatar']}})

@socketio.on('ban_user')
def ban(data):
    admin = users_col.find_one({"nick": data['admin_nick']})
    if admin and admin.get('rank') in ["Админ", "Модератор"]:
        users_col.update_one({"nick": data['target_nick']}, {"$set": {"banned": True}})
        emit('kick_signal', data['target_nick'], broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
