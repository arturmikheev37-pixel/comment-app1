from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB_PATH = "comments.db"

# ------------------ INIT DB ------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT,
            user_id TEXT,
            username TEXT,
            comment TEXT,
            created_at TEXT
        )
    ''')

    conn.commit()
    conn.close()

init_db()


# ------------------ HTML ------------------
HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Комментарии</title>

<style>
body {
    margin: 0;
    background: #0f0f0f;
    font-family: Arial;
}

.chat-container {
    display: flex;
    flex-direction: column;
    height: 100vh;
}

.messages {
    flex: 1;
    overflow-y: auto;
    padding: 15px;
}

/* сообщение */
.message {
    max-width: 75%;
    padding: 10px 14px;
    border-radius: 18px;
    margin-bottom: 10px;
    word-break: break-word;
}

/* чужие */
.message.other {
    background: #2a2a2a;
    color: white;
    align-self: flex-start;
}

/* мои */
.message.me {
    background: #667eea;
    color: white;
    align-self: flex-end;
}

/* имя */
.name {
    font-size: 12px;
    opacity: 0.7;
    margin-bottom: 4px;
}

/* время */
.time {
    font-size: 10px;
    opacity: 0.5;
    margin-top: 5px;
}

/* input */
.input-bar {
    display: flex;
    padding: 10px;
    background: #1a1a1a;
}

.input-bar input {
    flex: 1;
    padding: 12px;
    border-radius: 20px;
    border: none;
    outline: none;
}

.input-bar button {
    margin-left: 10px;
    padding: 0 16px;
    border-radius: 20px;
    border: none;
    background: #667eea;
    color: white;
    cursor: pointer;
}
</style>
</head>

<body>

<div class="chat-container">

    <div id="commentsList" class="messages"></div>

    <div class="input-bar">
        <input id="commentInput" placeholder="Написать комментарий..." />
        <button onclick="sendComment()">➤</button>
    </div>

</div>

<script>
// ---------------- USER (MAX) ----------------
let user = {
    id: null,
    name: "User"
};

// 🔥 если есть MAX — используем его
if (window.MAX && MAX.user) {
    user.id = MAX.user.id;
    user.name = MAX.user.first_name;
} else {
    // fallback
    user.id = localStorage.getItem("user_id") || Date.now();
    user.name = "User_" + user.id;
    localStorage.setItem("user_id", user.id);
}


// ---------------- POST ID ----------------
const post_id = new URLSearchParams(window.location.search).get("post") || "post_1";


// ---------------- LOAD ----------------
async function loadComments() {
    const res = await fetch(`/api/comments/${post_id}`);
    const data = await res.json();

    const list = document.getElementById("commentsList");
    list.innerHTML = "";

    data.comments.forEach(c => {
        const div = document.createElement("div");

        const isMe = c.user_id == user.id;

        div.className = "message " + (isMe ? "me" : "other");

        div.innerHTML = `
            ${!isMe ? `<div class="name">${c.username}</div>` : ""}
            <div>${c.comment}</div>
            <div class="time">${new Date(c.created_at).toLocaleString()}</div>
            ${isMe ? `<div onclick="deleteComment(${c.id})" style="font-size:10px;cursor:pointer;">Удалить</div>` : ""}
        `;

        list.appendChild(div);
    });

    list.scrollTop = list.scrollHeight;
}


// ---------------- SEND ----------------
async function sendComment() {
    const input = document.getElementById("commentInput");
    const text = input.value.trim();

    if (!text) return;

    await fetch('/api/comment', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            post_id,
            user_id: user.id,
            username: user.name,comment: text
        })
    });

    input.value = "";
    loadComments();
}


// ---------------- DELETE ----------------
async function deleteComment(id) {
    await fetch('/api/comment/' + id, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ user_id: user.id })
    });

    loadComments();
}


// ---------------- AUTO UPDATE ----------------
setInterval(loadComments, 2000);
loadComments();


// ENTER SEND
document.getElementById("commentInput").addEventListener("keypress", function(e) {
    if (e.key === "Enter") {
        sendComment();
    }
});
</script>

</body>
</html>
"""


# ------------------ ROUTES ------------------
@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/comments/<post_id>')
def get_comments(post_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, user_id, username, comment, created_at
        FROM comments
        WHERE post_id = ?
        ORDER BY id ASC
    ''', (post_id,))

    rows = cursor.fetchall()
    conn.close()

    comments = [{
        'id': r[0],
        'user_id': r[1],
        'username': r[2],
        'comment': r[3],
        'created_at': r[4]
    } for r in rows]

    return jsonify({'comments': comments})


@app.route('/api/comment', methods=['POST'])
def add_comment():
    data = request.get_json()

    post_id = data.get('post_id')
    user_id = data.get('user_id')
    username = data.get('username')
    comment = data.get('comment')

    if not all([post_id, user_id, username, comment]):
        return jsonify({'error': 'Missing fields'}), 400

    if len(comment) > 500:
        return jsonify({'error': 'Too long'}), 400

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO comments (post_id, user_id, username, comment, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (post_id, user_id, username, comment, datetime.now().isoformat()))

    conn.commit()
    conn.close()

    return jsonify({'status': 'success'})


@app.route('/api/comment/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    data = request.get_json()
    user_id = data.get('user_id')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('DELETE FROM comments WHERE id = ? AND user_id = ?', (comment_id, user_id))

    conn.commit()
    conn.close()

    return jsonify({'status': 'success'})


# ------------------ RUN ------------------
if __name__ == '__main__':
    app.run(debug=True, port=8000)
