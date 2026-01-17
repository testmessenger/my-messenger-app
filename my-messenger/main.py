from gevent import monkey
monkey.patch_all()
import os, time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100*1024*1024)

client = MongoClient("mongodb+srv://adminbase:admin123@cluster0.iw8h40a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0&tlsAllowInvalidCertificates=true")
db = client['messenger_db']
users_col, messages_col, rooms_col = db['users'], db['messages'], db['rooms']

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('login_attempt')
def login(data):
    nick = data['nick'].replace('@', '').lower()
    user = users_col.find_one({"nick": nick})
    if not user:
        users_col.insert_one({"nick": nick, "password": data['pass'], "name": data['name'], "avatar": ""})
    emit('login_success', {"name": data.get('name', nick), "nick": nick})

@socketio.on('search')
def search(data):
    q = data['query'].lower()
    users = list(users_col.find({"nick": {"$regex": q}}, {"_id":0, "password":0}))
    rooms = list(rooms_col.find({"name": {"$regex": q}}, {"_id":0}))
    emit('search_results', {"users": users, "rooms": rooms})

@socketio.on('create_room')
def create_room(data):
    # Добавляем список админов, по умолчанию создатель - владелец
    data['admins'] = [data['creator']]
    rooms_col.update_one({"id": data['id']}, {"$set": data}, upsert=True)
    emit('room_created', data, broadcast=True)

@socketio.on('delete_room_global')
def del_room(data):
    room = rooms_col.find_one({"id": data['room']})
    if room and room['creator'] == data['nick']:
        rooms_col.delete_one({"id": data['room']})
        messages_col.delete_many({"room": data['room']})
        emit('room_deleted_event', data['room'], broadcast=True)

@socketio.on('message')
def msg(data):
    res = messages_col.insert_one(data)
    data['_id'] = str(res.inserted_id)
    emit('render_message', data, to=data['room'])

@socketio.on('join')
def join(data):
    join_room(data['room'])
    history = list(messages_col.find({"room": data['room']}).sort("_id", -1).limit(50))
    for m in history: m['_id'] = str(m['_id'])
    emit('history', history[::-1])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
