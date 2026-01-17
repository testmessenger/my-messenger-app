import eventlet
eventlet.monkey_patch()

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ultra-elite-2026'
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

@socketio.on('login_attempt')
def handle_login(data):
    nick = data['nick'].replace('@', '').lower()
    user = users_col.find_one({"nick": nick})
    if user:
        if user['password'] == data['pass']:
            emit('login_success', {"name": user['name'], "nick": nick, "avatar": user.get('avatar', '')})
        else: emit('login_error', "Неверный пароль!")
    else:
        users_col.insert_one({"nick": nick, "password": data['pass'], "name": data['name'], "avatar": "", "last_seen": time.time()})
        emit('login_success', {"name": data['name'], "nick": nick, "avatar": ""})

@socketio.on('message')
def handle_message(data):
    data['time'] = time.time()
    data['reactions'] = {} # Формат: {"👍": ["user1", "user2"], "❤️": ["user3"]}
    user = users_col.find_one({"nick": data['nick'].replace('@','')})
    data['avatar'] = user.get('avatar', '') if user else ''
    res = messages_col.insert_one(data.copy())
    data['_id'] = str(res.inserted_id)
    emit('render_message', data, to=data['room'])

@socketio.on('add_reaction')
def add_reaction(data):
    msg_id = data['msg_id']
    emoji = data['emoji']
    user_nick = data['nick']
    
    msg = messages_col.find_one({"_id": ObjectId(msg_id)})
    if msg:
        reactions = msg.get('reactions', {})
        # Если юзер уже ставил этот эмодзи — убираем, если нет — добавляем
        if emoji in reactions:
            if user_nick in reactions[emoji]: reactions[emoji].remove(user_nick)
            else: reactions[emoji].append(user_nick)
            if not reactions[emoji]: del reactions[emoji]
        else:
            reactions[emoji] = [user_nick]
        
        messages_col.update_one({"_id": ObjectId(msg_id)}, {"$set": {"reactions": reactions}})
        emit('update_reactions', {"msg_id": msg_id, "reactions": reactions}, to=data['room'])

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    history = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(40))
    for m in history: m['_id'] = str(m['_id'])
    emit('history', history[::-1])

@socketio.on('update_status')
def update_status(data):
    users_col.update_one({"nick": data['nick'].replace('@','')}, {"$set": {"last_seen": time.time()}})

@socketio.on('delete_msg_global')
def delete_msg(data):
    messages_col.delete_one({"_id": ObjectId(data['msg_id'])})
    emit('msg_deleted_confirm', data, to=data['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
