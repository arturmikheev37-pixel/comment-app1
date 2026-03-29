from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB_PATH = "comments.db"

# ---------------- DB ----------------
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

# ---------------- HTML ----------------
HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Комментарии</title>

<style>
body {
    margin: 0;
    background: #f4f6fb;
    font-family: -apple-system, Arial;
}

.chat {
    display: flex;
    flex-direction: column;
    height: 100vh;
}

.messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
}

.msg {
    max-width: 75%;
    padding: 10px 14px;
    border-radius: 16px;
    margin-bottom: 10px;
    font-size: 14px;
}

.other {
    background: #fff;
}

.me {
    background: #4e6cff;
    color: white;
    margin-left: auto;
}

.name {
    font-size: 12px;
    font-weight: bold;
    margin-bottom: 3px;
}

.time {
    font-size: 10px;
    opacity: 0.6;
}

.input {
    display: flex;
    padding: 10px;
    background: white;
    border-top: 1px solid #ddd;
}

.input input {
    flex: 1;
    padding: 10px;
    border-radius: 20px;
    border: 1px solid #ccc;
}

.input button {
    margin-left: 10px;
    border: none;
    border-radius: 20px;
    padding: 0 15px;
    background: #4e6cff;
    color: white;
    cursor: pointer;
}
</style>
</head>

<body>

<div class="chat">
    <div id="list" class="messages"></div>

    <div class="input">
        <input id="text" placeholder="Написать комментарий..." />
        <button id="sendBtn">➤</button>
    </div>
</div>

<script>

// -------- USER (MAX) --------
let user = {id: null, name: "User"};

try {
    if (window.MAX && MAX.WebApp) {
        MAX.WebApp.ready();
        const u = MAX.WebApp.initDataUnsafe.user;

        if (u) {
            user.id = u.id;
            user.name = (u.first_name || "") + " " + (u.last_name || "");
        } else throw "no user";
    } else throw "no max";

} catch {
    user.id = localStorage.getItem("uid") || Date.now();
    user.name = "User_" + user.id;
    localStorage.setItem("uid", user.id);
}

// -------- POST --------
const post_id = new URLSearchParams(location.search).get("post") || "post_1";

// -------- LOAD --------
async function load() {
    try {
        const res = await fetch(`/api/comments/${post_id}`);
        const data = await res.json();

        const list = document.getElementById("list");
        list.innerHTML = "";

        data.comments.forEach(c => {
            const div = document.createElement("div");

            const me = c.user_id == user.id;
            div.className = "msg " + (me ? "me" : "other");

            div.innerHTML = `
                ${!me ? `<div class="name">${c.username}</div>` : ""}
                <div>${c.comment}</div>
                <div class="time">${new Date(c.created_at).toLocaleTimeString()}</div>
            `;

            list.appendChild(div);
        });

        list.scrollTop = list.scrollHeight;

    } catch (e) {
        console.log("LOAD ERROR", e);
    }
}

// -------- SEND --------
async function send() {
    const input = document.getElementById("text");
    const btn = document.getElementById("sendBtn");

    const text = input.value.trim();
    if (!text) return;

    btn.disabled = true;

    try {
        const res = await fetch("/api/comment", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                post_id,
                user_id: user.id,
                username: user.name,
                comment: text})
        });

        const data = await res.json();

        if (data.error) {
            alert(data.error);
        } else {
            input.value = "";
            load();
        }

    } catch (e) {
        alert("Ошибка отправки");
        console.log(e);
    }

    btn.disabled = false;
}

// -------- EVENTS --------
document.getElementById("sendBtn").onclick = send;

document.getElementById("text").addEventListener("keypress", e => {
    if (e.key === "Enter") send();
});

// -------- AUTO --------
setInterval(load, 2000);
load();

</script>

</body>
</html>
"""

# ---------------- ROUTES ----------------
@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/comments/<post_id>')
def comments(post_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id, user_id, username, comment, created_at FROM comments WHERE post_id=? ORDER BY id", (post_id,))
    rows = cur.fetchall()
    conn.close()

    return jsonify({
        "comments": [
            {"id":r[0],"user_id":r[1],"username":r[2],"comment":r[3],"created_at":r[4]}
            for r in rows
        ]
    })

@app.route('/api/comment', methods=['POST'])
def add():
    d = request.get_json()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO comments (post_id,user_id,username,comment,created_at) VALUES (?,?,?,?,?)",
        (d["post_id"], d["user_id"], d["username"], d["comment"], datetime.now().isoformat())
    )

    conn.commit()
    conn.close()

    return jsonify({"ok": True})

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)
