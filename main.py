from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB_PATH = "comments.db"


# ---------------- DB ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT,
            user_id TEXT,
            username TEXT,
            comment TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


init_db()

# ---------------- HTML ----------------
HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>Комментарии</title>

<style>

/* ---------- BACKGROUND ---------- */
body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, Arial;

    background:
        radial-gradient(circle at 20% 20%, rgba(255,255,255,0.4) 2px, transparent 2px),
        radial-gradient(circle at 80% 40%, rgba(255,255,255,0.3) 2px, transparent 2px),
        radial-gradient(circle at 40% 80%, rgba(255,255,255,0.2) 2px, transparent 2px),
        linear-gradient(135deg, #dfe9f3, #ffffff);
}

/* ---------- LAYOUT ---------- */
.chat {
    display: flex;
    flex-direction: column;
    height: 100vh;
}

.messages {
    flex: 1;
    overflow-y: auto;
    padding: 10px;
}

/* ---------- MESSAGE ---------- */
.msg {
    max-width: 80%;
    padding: 8px 12px;
    border-radius: 16px;
    margin-bottom: 8px;
    position: relative;
    word-wrap: break-word;
    font-size: 14px;
}

/* чужие */
.other {
    background: white;
    align-self: flex-start;
    border-bottom-left-radius: 4px;
}

/* мои */
.me {
    background: #dcf8c6;
    align-self: flex-end;
    border-bottom-right-radius: 4px;
}

/* имя */
.name {
    font-size: 12px;
    font-weight: 600;
    color: #555;
    margin-bottom: 2px;
}

/* текст */
.text {
    display: inline-block;
}

/* время */
.time {
    font-size: 10px;
    color: #777;
    margin-left: 6px;
}

/* ---------- INPUT ---------- */
.input {
    display: flex;
    padding: 8px;
    background: #f7f7f7;
    border-top: 1px solid #ddd;
}

.input input {
    flex: 1;
    padding: 10px 14px;
    border-radius: 20px;
    border: none;
    outline: none;
    background: white;
    font-size: 14px;
}

/* кнопка */
.input button {
    margin-left: 8px;
    border: none;
    border-radius: 50%;
    width: 40px;
    height: 40px;
    background: #4caf50;
    color: white;
    font-size: 16px;
    cursor: pointer;
}

/* ---------- MOBILE FIX ---------- */
@media (max-width: 600px) {
    .msg {
        max-width: 90%;
        font-size: 15px;
    }

    .input input {
        font-size: 16px;
    }
}

</style>
</head>

<body>

<div class="chat">
    <div id="list" class="messages"></div>

    <div class="input">
        <input id="text" placeholder="Сообщение..." />
        <button onclick="send()">➤</button>
    </div>
</div>

<script>

// ---------- USER ----------
let user = {id:null,name:"User"};

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

// ---------- POST ----------
const post_id = new URLSearchParams(location.search).get("post") || "post_1";

// ---------- LOAD ----------
async function load() {
    const res = await fetch(`/api/comments/${post_id}`);
    const data = await res.json();

    const list = document.getElementById("list");
    list.innerHTML = "";

    data.comments.forEach(c => {
        const div = document.createElement("div");const me = c.user_id == user.id;

        div.className = "msg " + (me ? "me" : "other");

        div.innerHTML = `
            ${!me ? `<div class="name">${c.username}</div>` : ""}
            <span class="text">${c.comment}</span>
            <span class="time">${new Date(c.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span>
        `;

        list.appendChild(div);
    });

    list.scrollTop = list.scrollHeight;
}

// ---------- SEND ----------
async function send() {
    const input = document.getElementById("text");
    const text = input.value.trim();
    if (!text) return;

    try {
        await fetch("/api/comment", {
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({
                post_id,
                user_id:user.id,
                username:user.name,
                comment:text
            })
        });

        input.value="";
        load();

    } catch(e) {
        alert("Ошибка отправки");
    }
}

// ---------- ENTER ----------
document.getElementById("text").addEventListener("keypress", e=>{
    if(e.key==="Enter") send();
});

// ---------- AUTO ----------
setInterval(load,2000);
load();

</script>

</body>
</html>
"""

# ---------------- API ----------------
@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/comments/<post_id>')
def get_comments(post_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT id,user_id,username,comment,created_at FROM comments WHERE post_id=? ORDER BY id", (post_id,))
    rows = c.fetchall()
    conn.close()

    return jsonify({"comments":[
        {"id":r[0],"user_id":r[1],"username":r[2],"comment":r[3],"created_at":r[4]}
        for r in rows
    ]})

@app.route('/api/comment', methods=['POST'])
def add():
    d = request.get_json()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        "INSERT INTO comments (post_id,user_id,username,comment,created_at) VALUES (?,?,?,?,?)",
        (d["post_id"], d["user_id"], d["username"], d["comment"], datetime.now().isoformat())
    )

    conn.commit()
    conn.close()

    return jsonify({"ok":True})

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)
