from gevent import monkey
monkey.patch_all()

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, disconnect
from pymongo import MongoClient

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=20 * 1024 * 1024)

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
    user = users_col.find_one({"nick": nick})
    
    if user:
        if user.get('banned'):
            emit('login_error', "Ваш аккаунт заблокирован!")
            return
        if user['password'] == password:
            emit('login_success', {"name": user['name'], "nick": nick, "avatar": user.get('avatar', ''), "rank": user.get('rank', 'Участник')})
        else: emit('login_error', "Неверный пароль!")
    else:
        rank = "Админ" if users_col.count_documents({}) == 0 else "Участник"
        users_col.insert_one({"nick": nick, "password": password, "name": data.get('name') or nick, "avatar": "", "rank": rank, "banned": False})
        emit('login_success', {"name": data.get('name') or nick, "nick": nick, "avatar": "", "rank": rank})

@socketio.on('get_members')
def get_members(data):
    members = []
    for u in users_col.find({"banned": {"$ne": True}}):
        members.append({"nick": u['nick'], "name": u['name'], "rank": u.get('rank', 'Участник'), "avatar": u.get('avatar', '')})
    emit('members_list', members)

@socketio.on('change_rank')
def change_rank(data):
    # data: { target_nick, new_rank, admin_nick }
    admin = users_col.find_one({"nick": data['admin_nick']})
    if admin and admin.get('rank') == "Админ":
        users_col.update_one({"nick": data['target_nick']}, {"$set": {"rank": data['new_rank']}})
        emit('system_message', f"Ранг @{data['target_nick']} изменен на {data['new_rank']}", broadcast=True)
        # Перезапрашиваем список участников у всех
        members = [{"nick": u['nick'], "name": u['name'], "rank": u.get('rank', 'Участник')} for u in users_col.find({"banned": {"$ne": True}})]
        emit('members_list', members, broadcast=True)

@socketio.on('ban_user')
def ban_user(data):
    # data: { target_nick, admin_nick }
    admin = users_col.find_one({"nick": data['admin_nick']})
    if admin and admin.get('rank') in ["Админ", "Модератор"]:
        target = users_col.find_one({"nick": data['target_nick']})
        if target and target.get('rank') == "Админ": return # Админа нельзя банить
        
        users_col.update_one({"nick": data['target_nick']}, {"$set": {"banned": True}})
        emit('system_message', f"Пользователь @{data['target_nick']} забанен!", broadcast=True)
        emit('kick_signal', data['target_nick'], broadcast=True)

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
    h = []
    for m in messages_col.find({"room": data['room']}).sort("_id", -1).limit(50):
        m.pop('_id', None)
        h.append(m)
    emit('history', h[::-1])

@socketio.on('get_rooms')
def get_rooms():
    rooms = [ {k:v for k,v in r.items() if k != '_id'} for r in rooms_col.find({}) ]
    emit('load_rooms', rooms)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
