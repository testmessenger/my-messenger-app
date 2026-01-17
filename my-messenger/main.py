import os
import time
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tg_clone_secret'
# Увеличиваем лимит на загрузку файлов (стандартно 16MB, можно менять)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=1000 * 1024 * 1024)

messages_db = []

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('message')
def handle_message(data):
    msg_id = str(int(time.time() * 1000))
    # Типы: 'text', 'file', 'image', 'video', 'note' (кружочек)
    new_msg = {
        'id': msg_id,
        'user': data['user'],
        'type': data.get('type', 'text'),
        'content': data.get('content'), # Текст или бинарные данные
        'filename': data.get('filename', '')
    }
    messages_db.append(new_msg)
    emit('render_message', new_msg, broadcast=True)

@socketio.on('delete_msg')
def handle_delete(msg_id):
    global messages_db
    messages_db = [m for m in messages_db if m['id'] != msg_id]
    emit('remove_from_ui', msg_id, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
