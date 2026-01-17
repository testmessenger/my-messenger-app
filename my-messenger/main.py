import eventlet
eventlet.monkey_patch()

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'litegram-ultra-2026'
# Увеличиваем буфер для передачи видео/аудио
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024)

# ИСПРАВЛЕННАЯ СТРОКА (с параметром SSL)
MONGO_URL = "mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true"
client = MongoClient(MONGO_URL)
db = client['messenger_db']

users_col = db['users']
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
        else:
            emit('login_error', "Неверный пароль!")
    else:
        new_user = {"nick": nick, "password": data['pass'], "name": data['name'], "avatar": "", "last_seen": time.time()}
        users_col.insert_one(new_user)
        emit('login_success', {"name": data['name'], "nick": nick, "avatar": ""})

@socketio.on('message')
def handle_message(data):
    data['time'] = time.time()
    data['reactions'] = {}
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
        if emoji in reactions:
            if user_nick in reactions[emoji]: reactions[emoji].remove(user_nick)
            else: reactions[emoji].append(user_nick)
            if not reactions[emoji]: del reactions[emoji]
        else:
            reactions[emoji] = [user_nick]
        messages_col.update_one({"_id": ObjectId(msg_id)}, {"$set": {"reactions": reactions}})
        emit('update_reactions', {"msg_id": msg_id, "reactions": reactions}, to=data['room'])

@socketio.on('delete_msg_global')
def delete_msg(data):
    messages_col.delete_one({"_id": ObjectId(data['msg_id'])})
    emit('msg_deleted_confirm', data, to=data['room'])

@socketio.on('join')
def on_join(data):
    join_room(data['room'])
    history = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(50))
    for m in history: m['_id'] = str(m['_id'])
    emit('history', history[::-1])

@socketio.on('update_status')
def update_status(data):
    users_col.update_one({"nick": data['nick'].replace('@','')}, {"$set": {"last_seen": time.time()}})

# СИГНАЛИНГ ДЛЯ ВИДЕОЗВОНКОВ
@socketio.on('join_call')
def handle_join_call(data):
    room = data['room'] + "_video"
    join_room(room)
    emit('user_joined_call', {'nick': data['nick']}, room=room, include_self=False)

@socketio.on('call_signal')
def handle_call_signal(data):
    emit('call_signal', {'from': data['from'], 'signal': data['signal']}, room=data['to'])

@socketio.on('update_avatar')
def update_avatar(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"avatar": data['avatar']}})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
