import eventlet
eventlet.monkey_patch()

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ultra-secure-2026'
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024)

MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URL)
db = client['messenger_db']

users_col = db['users']
rooms_col = db['rooms']
messages_col = db['messages']

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('update_status')
def update_status(data):
    nick = data['nick'].replace('@', '')
    users_col.update_one({"nick": nick}, {"$set": {"last_seen": time.time()}})
    user = users_col.find_one({"nick": nick})
    if user:
        emit('status_updated', {"nick": nick, "last_seen": user.get('last_seen', 0)}, broadcast=True)

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
        users_col.insert_one({"nick": nick, "password": data['pass'], "name": data['name'], "last_seen": time.time()})
        emit('login_success', {"name": data['name'], "nick": nick})

@socketio.on('join')
def on_join(data):
    room_name = data['room']
    join_room(room_name)
    history = list(messages_col.find({"room": room_name}).sort("_id", -1).limit(40))
    for m in history: m['_id'] = str(m['_id'])
    emit('history', history[::-1])
    
    room_data = rooms_col.find_one({"name": room_name})
    if room_data:
        room_data['_id'] = str(room_data['_id'])
        emit('room_info', room_data, to=room_name)

@socketio.on('message')
def handle_message(data):
    data['time'] = time.time()
    res = messages_col.insert_one(data.copy())
    data['_id'] = str(res.inserted_id)
    emit('render_message', data, to=data['room'])

@socketio.on('search_user')
def search_user(data):
    query = data['query'].replace('@', '').lower()
    u = users_col.find_one({"nick": query})
    if u: emit('user_found', {"nick": u['nick'], "name": u['name'], "last_seen": u.get('last_seen', 0)})
    else: emit('login_error', "Пользователь не найден")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
