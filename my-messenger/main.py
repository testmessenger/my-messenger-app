import eventlet
eventlet.monkey_patch()

import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=1000 * 1024 * 1024)

# База данных чатов с ролями
rooms_db = {
    "Общий чат": {
        "type": "group",
        "owner": "system",
        "admins": [],
        "members": []
    }
}

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def on_join(data):
    room_name = data['room']
    user_nick = data['nick']
    join_room(room_name)
    
    if room_name in rooms_db:
        if user_nick not in rooms_db[room_name]['members']:
            rooms_db[room_name]['members'].append(user_nick)
    
    # Отправляем инфо о комнате (состав участников)
    emit('room_info', rooms_db.get(room_name, {}), to=room_name)

@socketio.on('create_room')
def create_room(data):
    name = data['name']
    rooms_db[name] = {
        "type": data['type'],
        "owner": data['user'], # Тот кто создал - Владелец
        "admins": [],
        "members": [data['user']]
    }
    emit('room_created', {"name": name}, broadcast=True)

@socketio.on('make_admin')
def make_admin(data):
    room = data['room']
    target = data['target']
    requester = data['requester']
    
    # Проверка: только владелец может назначать админов
    if rooms_db[room]['owner'] == requester:
        if target not in rooms_db[room]['admins']:
            rooms_db[room]['admins'].append(target)
            emit('room_info', rooms_db[room], to=room)
            emit('notification', f"{target} теперь администратор!", to=room)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
