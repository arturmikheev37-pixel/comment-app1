from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB = "db.db"

# ---------------- DB ----------------
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT,
        user_id TEXT,
        username TEXT,
        comment TEXT,
        likes INTEGER DEFAULT 0,
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
body {
    margin:0;
    font-family:-apple-system, Arial, sans-serif;
    background:#f0f0f5;
}

/* HEADER */
.header {
    background:#1c1c1e;
    color:white;
    padding:14px;
    text-align:center;
    font-weight:600;
    position:relative;
}

.header .left {
    position:absolute;
    left:10px;
    top:12px;
    font-size:22px;
    cursor:pointer;
}

.header .right {
    position:absolute;
    right:10px;
    top:12px;
    font-size:20px;
    cursor:pointer;
}

/* POST */
.post {
    background:white;
    padding:12px;
    display:flex;
    align-items:center;
    border-bottom:1px solid #ddd;
}

.avatar {
    width:40px;
    height:40px;
    border-radius:50%;
    background:#4e6cff;
    margin-right:12px;
    flex-shrink:0;
}

.post-title {
    font-weight:600;
    margin-bottom:2px;
}

.post-count {
    font-size:12px;
    color:gray;
}

/* CHAT */
.chat {
    height:calc(100vh - 160px);
    overflow-y:auto;
    padding:10px;
}

/* MESSAGE */
.msg {
    display:flex;
    margin-bottom:10px;
}

.bubble {
    background:white;
    padding:10px 14px;
    border-radius:18px;
    margin-left:8px;
    max-width:80%;
    position:relative;
    box-shadow:0 1px 2px rgba(0,0,0,0.1);
}

.name {
    font-size:13px;
    color:#333;
    font-weight:600;
    margin-bottom:2px;
}

.text {
    font-size:14px;
    color:#222;
}

.time {
    font-size:11px;
    color:#888;
    margin-top:4px;
    display:flex;
    align-items:center;
    justify-content:flex-start;
}

.reply, .like, .share {
    font-size:12px;
    color:#4e6cff;
    cursor:pointer;
    margin-left:10px;
}

/* INPUT */
.input {
    position:fixed;
    bottom:0;
    width:100%;
    background:#fff;
    display:flex;
    align-items:center;
    padding:8px 10px;
    border-top:1px solid #ccc;
}

.input input {
    flex:1;
    border:none;
    border-radius:20px;
    padding:10px 14px;
    margin-right:8px;
    background:#f1f1f5;
    font-size:14px;
}

.input input:focus {
    outline:none;
}

.icon {
    font-size:22px;
    cursor:pointer;
    margin-left:4px;
}
</style>
</head>

<body>

<div class="header">
    <div class="left" onclick="window.close()">✕</div>
    Комментарии (<span id="count">0</span>)
    <div class="right">⋯</div>
</div>

<div class="post">
    <div class="avatar"></div>
    <div>
        <div class="post-title">Мой пост</div>
        <div class="post-count" id="postCount">0 комментариев</div>
    </div>
</div>

<div id="chat" class="chat"></div>

<div class="input">
    <input id="text" placeholder="Написать комментарий..." />
    <div class="icon" onclick="send()">➤</div>
</div>

<script>
// USER (MAX fallback)
let user = {id:null,name:"User"};

try {
    if (window.MAX && MAX.WebApp) {
        MAX.WebApp.ready();
        const u = MAX.WebApp.initDataUnsafe.user;
        if (u) {
            user.id = u.id;
            user.name = (u.first_name || "") + " " + (u.last_name || "");
        }
    }
} catch {}

if (!user.id) {
    user.id = localStorage.getItem("uid") || Date.now();
    user.name = "User_" + user.id;
    localStorage.setItem("uid", user.id);
}

// POST
const post_id = new URLSearchParams(location.search).get("post") || "post_1";

// LOAD COMMENTSasync function load() {
    const res = await fetch(`/api/comments/${post_id}`);
    const data = await res.json();

    const chat = document.getElementById("chat");
    chat.innerHTML = "";

    document.getElementById("count").innerText = data.comments.length;
    document.getElementById("postCount").innerText = data.comments.length + " комментариев";

    data.comments.forEach(c => {
        const div = document.createElement("div");
        div.className = "msg";

        div.innerHTML = `
            <div class="avatar"></div>
            <div class="bubble">
                <div class="name">${c.username}</div>
                <div class="text">${c.comment}</div>
                <div class="time">
                    ${new Date(c.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}
                    <span class="reply" onclick="reply('${c.username}')">↩ Ответ</span>
                    <span class="like" onclick="like(this)">❤ ${c.likes}</span>
                    <span class="share" onclick="share('${c.comment}')">⇪</span>
                </div>
            </div>
        `;

        chat.appendChild(div);
    });

    chat.scrollTop = chat.scrollHeight;
}

// SEND COMMENT
async function send() {
    const input = document.getElementById("text");
    const text = input.value.trim();
    if (!text) return;

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
}

// REPLY
function reply(name){
    const input = document.getElementById("text");
    input.value = "@" + name + " ";
    input.focus();
}

// LIKE
function like(el){
    let count = parseInt(el.innerText.replace(/[^0-9]/g,'')) || 0;
    el.innerText = "❤ " + (count + 1);
}

// SHARE
function share(text){
    navigator.clipboard.writeText(text).then(()=>alert("Комментарий скопирован!"));
}

// ENTER
document.getElementById("text").addEventListener("keypress", e=>{
    if(e.key==="Enter") send();
});

// AUTOLOAD
setInterval(load,2000);
load();
</script>

</body>
</html>
"""

# ---------------- ROUTES ----------------
@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/comments/<post_id>")
def get_comments(post_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT id,user_id,username,comment,likes,created_at FROM comments WHERE post_id=? ORDER BY id", (post_id,))
    rows = c.fetchall()
    conn.close()

    return jsonify({"comments":[
        {"id":r[0],"user_id":r[1],"username":r[2],"comment":r[3],"likes":r[4],"created_at":r[5]}
        for r in rows
    ]})

@app.route("/api/comment", methods=["POST"])
def add_comment():
    d = request.get_json()

    conn = sqlite3.connect(DB)
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
