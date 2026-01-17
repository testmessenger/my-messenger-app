import eventlet
eventlet.monkey_patch() # КРИТИЧЕСКИ ВАЖНО: всегда первая строка

import os
import time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'messenger_2026_key'

# Настройка для передачи больших файлов (до 1 ГБ)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=1000 * 1024 * 1024)

# Временное хранилище (в памяти)
messages_db = []

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('message')
def handle_message(data):
    msg_id = str(int(time.time() * 1000))
    
    # Структура сообщения: текст, фото, видео или файл
    new_msg = {
        'id': msg_id,
        'user': data.get('user', 'Аноним'),
        'type': data.get('type', 'text'),
        'content': data.get('content'), # Текст или Base64 данные файла
        'filename': data.get('filename', '')
    }
    
    messages_db.append(new_msg)
    # Рассылаем всем пользователям
    emit('render_message', new_msg, broadcast=True)

@socketio.on('delete_msg')
def handle_delete(msg_id):
    global messages_db
    messages_db = [m for m in messages_db if m['id'] != msg_id]
    emit('remove_from_ui', msg_id, broadcast=True)

if __name__ == '__main__':
    # На Render порт берется из переменной окружения
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
