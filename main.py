from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB_PATH = "comments.db"

# ---------------- Инициализация базы ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Таблица комментариев
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
body {margin:0; font-family:-apple-system,BlinkMacSystemFont,Arial; background:#f0f2f5;}
.chat {display:flex; flex-direction:column; height:100vh;}
.messages {flex:1; overflow-y:auto; padding:10px;}
.msg {max-width:80%; padding:8px 12px; border-radius:16px; margin-bottom:8px; word-wrap:break-word; font-size:14px; position:relative;}
.other {background:white; align-self:flex-start; border-bottom-left-radius:4px;}
.me {background:#dcf8c6; align-self:flex-end; border-bottom-right-radius:4px;}
.name {font-size:12px; font-weight:600; color:#555; margin-bottom:2px;}
.text {display:inline-block;}
.time {font-size:10px; color:#777; margin-left:6px;}
.btn-edit, .btn-delete {font-size:10px; cursor:pointer; margin-left:4px; color:#007bff;}
.input {display:flex; padding:8px; background:#f7f7f7; border-top:1px solid #ddd;}
.input input {flex:1; padding:10px 14px; border-radius:20px; border:none; outline:none; background:white; font-size:14px;}
.input button {margin-left:8px; border:none; border-radius:50%; width:40px; height:40px; background:#4caf50; color:white; font-size:16px; cursor:pointer;}
@media (max-width:600px){.msg{max-width:90%; font-size:15px;}.input input{font-size:16px;}}
</style>
</head>
<body>
<div class="chat">
    <div id="list" class="messages"></div>
    <div class="input">
        <input id="text" placeholder="Комментарий..." />
        <button onclick="send()">➤</button>
    </div>
</div>
<script>
let user = {id:null, name:"User"};
try {
    if(window.MAX && MAX.WebApp){
        MAX.WebApp.ready();
        const u = MAX.WebApp.initDataUnsafe.user;
        if(u){user.id=u.id; user.name=(u.first_name||"")+" "+(u.last_name||"");}
    } else throw "no max";
}catch{user.id=localStorage.getItem("uid")||Date.now(); user.name="User_"+user.id; localStorage.setItem("uid",user.id);}
const post_id = new URLSearchParams(location.search).get("post") || "post_1";

async function load(){
    const res = await fetch(`/api/comments/${post_id}`);
    const data = await res.json();
    const list = document.getElementById("list"); list.innerHTML="";
    data.comments.forEach(c=>{
        const div=document.createElement("div");
        const me=c.user_id==user.id;
        div.className="msg "+(me?"me":"other");
        div.innerHTML=`${!me?`<div class="name">${c.username}</div>`:""}<span class="text">${c.comment}</span>
        <span class="time">${new Date(c.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span>
        ${me?`<span class="btn-edit" onclick="edit(${c.id},'${c.comment.replace(/'/g,"\\'")}')">✎</span>
        <span class="btn-delete" onclick="remove(${c.id})">🗑</span>`:""}`;
        list.appendChild(div);
    });
    list.scrollTop=list.scrollHeight;
}

async function send(){
    const input=document.getElementById("text");
    const text=input.value.trim(); if(!text) return;
    await fetch("/api/comment",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({post_id,user_id:user.id,username:user.name,comment:text})});
    input.value=""; load();
}

async function edit(id,old){
    const new_text = prompt("Редактировать комментарий:", old);
    if(new_text!==null && new_text.trim()!==""){
        await fetch("/api/comment/"+id,{method:"PUT",headers:{"Content-Type":"application/json"},
            body:JSON.stringify({comment:new_text.trim()})});
        load();
    }
}

async function remove(id){
    if(confirm("Удалить комментарий?")){
        await fetch("/api/comment/"+id,{method:"DELETE"});
        load();
    }
}

document.getElementById("text").addEventListener("keypress",e=>{if(e.key==="Enter") send();});
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
    conn=sqlite3.connect(DB_PATH)
    c=conn.cursor()
    c.execute("SELECT id,user_id,username,comment,created_at FROM comments WHERE post_id=? ORDER BY id",(post_id,))
    rows=c.fetchall()
    conn.close()
    return jsonify({"comments":[{"id":r[0],"user_id":r[1],"username":r[2],"comment":r[3],"created_at":r[4]} for r in rows]})

@app.route('/api/comment', methods=['POST'])
def add_comment():
    d=request.get_json()
    conn=sqlite3.connect(DB_PATH)
    c=conn.cursor()
    c.execute("INSERT INTO comments (post_id,user_id,username,comment,created_at) VALUES (?,?,?,?,?)",
              (d["post_id"],d["user_id"],d["username"],d["comment"],datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"ok":True})

@app.route('/api/comment/<int:id>', methods=['PUT'])
def edit_comment(id):
    d=request.get_json()
    conn=sqlite3.connect(DB_PATH)
    c=conn.cursor()
    c.execute("UPDATE comments SET comment=? WHERE id=?",(d["comment"],id))
    conn.commit(); conn.close()
    return jsonify({"ok":True})

@app.route('/api/comment/<int:id>', methods=['DELETE'])
def delete_comment(id):
    conn=sqlite3.connect(DB_PATH)
    c=conn.cursor()
    c.execute("DELETE FROM comments WHERE id=?",(id,))
    conn.commit(); conn.close()
    return jsonify({"ok":True})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080,debug=True)
