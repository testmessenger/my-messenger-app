from gevent import monkey
monkey.patch_all()
import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient

app = Flask(__name__)
# Увеличиваем лимит данных до 50МБ для видео и аудио
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024)

# Подключение к MongoDB
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
            emit('login_success', {"name": user['name'], "nick": nick, "avatar": user.get('avatar', ''), "rank": user.get('rank', 'Участник'), "bio": user.get('bio', '')})
        else: emit('login_error', "Неверный пароль!")
    else:
        new_u = {"nick": nick, "password": data['pass'], "name": nick, "avatar": "", "rank": "Участник", "bio": "", "banned": False}
        users_col.insert_one(new_u)
        emit('login_success', {"name": nick, "nick": nick, "avatar": "", "rank": "Участник", "bio": ""})

@socketio.on('message')
def handle_msg(data):
    data['id'] = str(os.urandom(8).hex())
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
    messages_col.update_one({"id": data['msg_id']}, {"$set": {f"reactions.{data['nick']}": data['emoji']}})
    msg = messages_col.find_one({"id": data['msg_id']}, {"_id":0})
    emit('update_reactions', msg, broadcast=True)

@socketio.on('call_signal')
def call_signal(data):
    # Передаем сигнал звонка другому пользователю
    emit('incoming_call', data, to=data['to_room'], include_self=False)

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    h = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(50))
    for m in h: m.pop('_id')
    emit('history', h[::-1])

@socketio.on('get_my_rooms')
def get_rooms(data):
    emit('load_rooms', list(rooms_col.find({"members": data['nick']}, {"_id": 0})))

@socketio.on('update_profile')
def up_prof(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"name": data['name'], "bio": data['bio'], "avatar": data['avatar']}})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
