from gevent import monkey
monkey.patch_all()

import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId # Добавили импорт для обработки ID

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=20 * 1024 * 1024)

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
    password = data['pass'].strip()
    name = data.get('name') or nick
    
    if not nick or not password:
        emit('login_error', "Заполните все поля!")
        return

    user = users_col.find_one({"nick": nick})
    if user:
        if user['password'] == password:
            # Убираем ObjectId перед отправкой
            user_data = {"name": user['name'], "nick": nick, "avatar": user.get('avatar', '')}
            emit('login_success', user_data)
        else:
            emit('login_error', "Неверный пароль!")
    else:
        users_col.insert_one({"nick": nick, "password": password, "name": name, "avatar": ""})
        emit('login_success', {"name": name, "nick": nick, "avatar": ""})

@socketio.on('get_rooms')
def get_rooms():
    # Находим все комнаты и превращаем их в список, убирая _id
    rooms = []
    for r in rooms_col.find({}):
        r.pop('_id', None) # Удаляем несериализуемый ID
        rooms.append(r)
    emit('load_rooms', rooms)

@socketio.on('create_room')
def create_r(data):
    if not rooms_col.find_one({"id": data['id']}):
        rooms_col.insert_one(data)
        # Копируем данные и удаляем _id перед вещанием
        broadcast_data = data.copy()
        broadcast_data.pop('_id', None)
        emit('room_created', broadcast_data, broadcast=True)

@socketio.on('search')
def search(data):
    q = data['query'].lower().strip()
    if not q: return
    
    # Ищем пользователей
    users = []
    for u in users_col.find({"nick": {"$regex": q}}):
        users.append({"nick": u['nick'], "name": u['name'], "avatar": u.get('avatar', '')})
        
    # Ищем комнаты
    rooms = []
    for r in rooms_col.find({"name": {"$regex": q, "$options": "i"}}):
        r.pop('_id', None)
        rooms.append(r)
        
    emit('search_results', {"users": users, "rooms": rooms})

@socketio.on('message')
def handle_msg(data):
    # Сохраняем в базу
    messages_col.insert_one(data)
    # ПЕРЕД ОТПРАВКОЙ удаляем _id, который добавила MongoDB
    data.pop('_id', None)
    emit('render_message', data, to=data['room'])

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)
    # Загружаем историю, превращая каждый объект в чистый словарь без _id
    h = []
    for m in messages_col.find({"room": room}).sort("_id", -1).limit(50):
        m.pop('_id', None)
        h.append(m)
    emit('history', h[::-1])

@socketio.on('update_profile_image')
def update_img(data):
    users_col.update_one({"nick": data['nick']}, {"$set": {"avatar": data['img']}})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
