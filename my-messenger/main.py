import eventlet
eventlet.monkey_patch()

import os
import time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pro-messenger-2026'
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=1000 * 1024 * 1024)

# ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ
# Замени ЭТУ ССЫЛКУ на свою из MongoDB Atlas!
MONGO_URL = "mongodb+srv://admin:ТВОЙ_ПАРОЛЬ@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority"
client = MongoClient(MONGO_URL)
db = client['messenger_db']

# Коллекции (таблицы) в базе
users_col = db['users']
rooms_col = db['rooms']
messages_col = db['messages']

# Создаем общий чат по умолчанию, если его нет
if not rooms_col.find_one({"name": "Общий чат"}):
    rooms_col.insert_one({
        "name": "Общий чат", 
        "type": "group", 
        "owner": "system", 
        "admins": [], 
        "members": []
    })

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def on_join(data):
    room_name = data['room']
    nick = data['nick']
    join_room(room_name)
    
    # Добавляем участника в базу чата
    rooms_col.update_one(
        {"name": room_name},
        {"$addToSet": {"members": nick}}
    )
    
    # Загружаем историю из базы
    history = list(messages_col.find({"room": room_name}).sort("_id", -1).limit(50))
    for m in history: m['_id'] = str(m['_id']) # Исправляем формат ID для JSON
    
    emit('history', history[::-1])
    
    # Рассылаем инфо о комнате из базы
    room_data = rooms_col.find_one({"name": room_name})
    room_data['_id'] = str(room_data['_id'])
    emit('room_info', room_data, to=room_name)

@socketio.on('message')
def handle_message(data):
    data['timestamp'] = time.time()
    # Сохраняем сообщение в базу навсегда
    messages_col.insert_one(data.copy())
    
    # Отправляем в чат (удаляем системный ID базы перед отправкой)
    if '_id' in data: del data['_id']
    emit('render_message', data, to=data.get('room'))

@socketio.on('create_room')
def create_room(data):
    name = data['name']
    if not rooms_col.find_one({"name": name}):
        new_room = {
            "name": name,
            "type": data['type'],
            "owner": data['user'],
            "admins": [],
            "members": [data['user']]
        }
        rooms_col.insert_one(new_room)
        emit('room_created', {"name": name}, broadcast=True)

@socketio.on('make_admin')
def make_admin(data):
    room = data['room']
    target = data['target']
    requester = data['requester']
    
    room_data = rooms_col.find_one({"name": room})
    if room_data and room_data['owner'] == requester:
        rooms_col.update_one(
            {"name": room},
            {"$addToSet": {"admins": target}}
        )
        updated_room = rooms_col.find_one({"name": room})
        updated_room['_id'] = str(updated_room['_id'])
        emit('room_info', updated_room, to=room)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
