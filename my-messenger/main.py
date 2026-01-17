from gevent import monkey
monkey.patch_all()
import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient

app = Flask(__name__)
# 50MB лимит для тяжелых медиа-данных (видео/аудио)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024)

MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URL, connect=False)
db = client['messenger_db']
users_col = db['users']
messages_col = db['messages']
rooms_col = db['rooms']

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('login_attempt')
def login(data):
    nick = data['nick'].replace('@', '').lower().strip()
    user = users_col.find_one({"nick": nick})
    if user:
        if user['password'] == data['pass']:
            emit('login_success', user_data(user))
        else: emit('login_error', "Ошибка пароля")
    else:
        new_u = {"nick": nick, "password": data['pass'], "name": nick, "avatar": "", "bio": "", "rank": "Участник"}
        users_col.insert_one(new_u)
        emit('login_success', user_data(new_u))

def user_data(u):
    return {"name": u.get('name'), "nick": u.get('nick'), "avatar": u.get('avatar'), "bio": u.get('bio'), "rank": u.get('rank')}

@socketio.on('update_profile')
def update_profile(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"name": data['name'], "bio": data['bio']}})
    emit('profile_updated', data, broadcast=True)

@socketio.on('get_user_info')
def get_user_info(data):
    u = users_col.find_one({"nick": data['nick']}, {"_id":0, "password":0})
    if u: emit('user_info_res', u)

@socketio.on('message')
def handle_msg(data):
    data['id'] = str(os.urandom(4).hex())
    data['reactions'] = {}
    messages_col.insert_one(data.copy())
    data.pop('_id', None)
    emit('render_message', data, to=data['room'])

@socketio.on('typing')
def handle_typing(data):
    emit('display_typing', data, to=data['room'], include_self=False)

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    h = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(40))
    for m in h: m.pop('_id')
    emit('history', h[::-1])

@socketio.on('get_members')
def get_members(data):
    # Упрощенная логика: все пользователи (в реале тут фильтр по комнате)
    m_list = list(users_col.find({}, {"_id":0, "password":0}).limit(50))
    emit('members_list', m_list)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
