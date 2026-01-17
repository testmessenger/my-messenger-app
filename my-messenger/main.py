from gevent import monkey
monkey.patch_all()
import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024)

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

@socketio.on('message')
def handle_msg(data):
    user = users_col.find_one({"nick": data['nick']})
    if user and not user.get('banned'):
        data['id'] = str(os.urandom(8).hex()) # Уникальный ID сообщения
        data['rank'] = user.get('rank', 'Участник')
        data['reactions'] = {}
        messages_col.insert_one(data.copy())
        data.pop('_id', None)
        emit('render_message', data, to=data['room'])

@socketio.on('delete_msg')
def delete_msg(data):
    messages_col.delete_one({"id": data['id'], "nick": data['nick']})
    emit('msg_deleted', data['id'], broadcast=True)

@socketio.on('add_reaction')
def add_reaction(data):
    # data: {msg_id, emoji, nick}
    messages_col.update_one({"id": data['msg_id']}, {"$set": {f"reactions.{data['nick']}": data['emoji']}})
    msg = messages_col.find_one({"id": data['msg_id']}, {"_id":0})
    emit('update_reactions', msg, broadcast=True)

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    h = [ {k:v for k,v in m.items() if k != '_id'} for m in messages_col.find({"room": data['room']}).sort("_id", -1).limit(50) ]
    emit('history', h[::-1])

@socketio.on('get_my_rooms')
def get_my_rooms(data):
    emit('load_rooms', list(rooms_col.find({"members": data['nick']}, {"_id": 0})))

@socketio.on('search')
def search(data):
    q = data['query'].lower().strip()
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

@socketio.on('get_members')
def get_m(data=None):
    if data and 'room' in data:
        room = rooms_col.find_one({"id": data['room']})
        if room and 'members' in room:
            m_list = list(users_col.find({"nick": {"$in": room['members']}}, {"_id":0, "password":0}))
            return emit('members_list', m_list)
    emit('members_list', list(users_col.find({"banned": {"$ne": True}}, {"_id":0, "password":0}).limit(20)))

@socketio.on('update_profile')
def update_profile(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"name": data['name'], "bio": data['bio'], "avatar": data['avatar']}})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
