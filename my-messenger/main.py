import eventlet
eventlet.monkey_patch()

import os
import time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=1000 * 1024 * 1024)

# В памяти будем хранить список созданных групп и каналов
rooms_db = {"Общий чат": {"type": "group"}}

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)
    print(f"User joined {room}")

@socketio.on('message')
def handle_message(data):
    room = data.get('room', 'Общий чат')
    msg_id = str(int(time.time() * 1000))
    data['id'] = msg_id
    # Отправляем сообщение только участникам этой комнаты
    emit('render_message', data, to=room)

@socketio.on('create_room')
def create_room(data):
    name = data['name']
    rooms_db[name] = {"type": data['type'], "owner": data['user']}
    emit('room_created', {"name": name, "type": data['type']}, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
