import eventlet
eventlet.monkey_patch()

import os
import time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-2026'
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=1000 * 1024 * 1024)

# Временная БД
rooms_db = {
    "Общий чат": {"type": "group", "owner": "system", "admins": [], "members": []}
}
messages_history = []

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def on_join(data):
    room = data['room']
    nick = data['nick']
    join_room(room)
    
    if room in rooms_db:
        if nick not in rooms_db[room]['members']:
            rooms_db[room]['members'].append(nick)
        
        # Отправляем историю только вошедшему
        room_msgs = [m for m in messages_history if m.get('room') == room]
        emit('history', room_msgs)
        
        # РАССЫЛКА ВСЕМ В ЧАТЕ: обновите список участников
        emit('room_info', rooms_db[room], to=room)

@socketio.on('message')
def handle_message(data):
    data['id'] = str(int(time.time() * 1000))
    messages_history.append(data)
    emit('render_message', data, to=data.get('room'))

@socketio.on('create_room')
def create_room(data):
    name = data['name']
    if name not in rooms_db:
        rooms_db[name] = {
            "type": data['type'],
            "owner": data['user'],
            "admins": [],
            "members": [data['user']]
        }
        # Рассылаем всем информацию о новом чате
        emit('room_created', {"name": name}, broadcast=True)

@socketio.on('make_admin')
def make_admin(data):
    room = data['room']
    target = data['target']
    if rooms_db[room]['owner'] == data['requester']:
        if target not in rooms_db[room]['admins']:
            rooms_db[room]['admins'].append(target)
            emit('room_info', rooms_db[room], to=room)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
