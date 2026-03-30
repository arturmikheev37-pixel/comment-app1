from flask import Flask, request, jsonify, render_template_string
from flask_socketio import SocketIO, emit, join_room
import sqlite3
from datetime import datetime
import json
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

DB_PATH = os.path.join(os.path.dirname(__file__), 'comments.db')

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT NOT NULL,
            parent_id INTEGER DEFAULT 0,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            comment TEXT NOT NULL,
            likes INTEGER DEFAULT 0,
            liked_by TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

init_db()

# ========== HTML (Telegram-стиль) ==========
HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
<title>Telegram Comments</title>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<style>
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto;
    background: url('https://telegram.org/img/tgme/pattern.svg') repeat;
    background-color: #0e1621;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.chat { max-width: 700px; margin: auto; height: 100vh; display: flex; flex-direction: column; width: 100%; }
.chat-header { padding: 12px 16px; background: #17212b; border-bottom: 1px solid #2a3947; flex-shrink: 0; }
.chat-title { font-weight: 600; font-size: 17px; display: flex; align-items: center; justify-content: center; gap: 8px; color: #ffffff; }
.chat-title span { background: #2a3947; padding: 2px 8px; border-radius: 12px; font-size: 11px; color: #8e8e93; }
.post-id { font-size: 10px; color: #8e8e93; margin-top: 4px; text-align: center; word-break: break-all; }
.messages { flex: 1; overflow-y: auto; padding: 12px; }
.message { display: flex; margin-bottom: 10px; animation: fadeIn 0.2s ease; }
.message.mine { flex-direction: row-reverse; }
.message.mine .avatar { margin-right: 0; margin-left: 8px; }
.message.mine .bubble { background: #2b5278; }
.avatar { width: 36px; height: 36px; border-radius: 50%; margin-right: 8px; flex-shrink: 0; object-fit: cover; }
.bubble { background: #182533; padding: 8px 10px; border-radius: 12px; max-width: 75%; position: relative; }
.name { font-size: 13px; font-weight: 600; color: #6ab3ff; }
.text { margin-top: 3px; font-size: 14px; color: #ffffff; word-break: break-word; }
.time { font-size: 11px; color: #aaa; text-align: right; margin-top: 4px; }
.reply { font-size: 12px; color: #6ab3ff; margin-bottom: 4px; border-left: 2px solid #6ab3ff; padding-left: 6px; cursor: pointer; }
.reactions { margin-top: 4px; font-size: 13px; display: flex; gap: 8px; }
.reactions span { cursor: pointer; color: #8e8e93; transition: color 0.2s; }
.reactions span:hover { color: #6ab3ff; }
.reactions .liked { color: #ff3b30; }
.replies-container { margin-left: 44px; margin-top: 8px; display: none; }
.reply-toggle { font-size: 12px; color: #6ab3ff; cursor: pointer; margin-left: 44px; margin-top: 4px; padding: 4px 0; display: inline-block; }
.input-area { display: flex; padding: 10px; background: #17212b; gap: 8px; flex-shrink: 0; border-top: 1px solid #2a3947; }
.input-wrapper { flex: 1; background: #2a3947; border-radius: 20px; padding: 10px 16px; }
.input-wrapper input { width: 100%; background: none; border: none; outline: none; color: white; font-size: 15px; font-family: inherit; }
.input-wrapper input::placeholder { color: #8e8e93; }
button { background: #2ea6ff; border: none; padding: 0 16px; border-radius: 20px; color: white; cursor: pointer; font-weight: 500; transition: opacity 0.2s; }
button:active { opacity: 0.7; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.reply-indicator { background: #2a3947; padding: 6px 12px; margin: 0 12px 4px 12px; border-radius: 20px; font-size: 12px; display: none; align-items: center; justify-content: space-between; }
.reply-indicator button { background: none; padding: 0 8px; color: #ff3b30; }
.empty-state { text-align: center; padding: 60px 20px; color: #8e8e93; }
.empty-state-icon { font-size: 48px; margin-bottom: 12px; }
.status { position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.8); color: white; padding: 8px 16px; border-radius: 20px; font-size: 13px; opacity: 0; transition: opacity 0.2s; pointer-events: none; z-index: 200; white-space: nowrap; }
.status.show { opacity: 1; }
.modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-content { background: #17212b; border-radius: 24px; padding: 24px; width: 90%; max-width: 320px; text-align: center; animation: modalFadeIn 0.3s ease; }
.modal-icon { font-size: 48px; margin-bottom: 16px; }
.modal-title { font-size: 20px; font-weight: 600; margin-bottom: 8px; color: #ffffff; }
.modal-desc { font-size: 14px; color: #8e8e93; margin-bottom: 20px; }
.modal-input { width: 100%; padding: 12px 16px; border: 1px solid #2a3947; border-radius: 12px; font-size: 16px; margin-bottom: 20px; outline: none; font-family: inherit; background: #2a3947; color: white; }
.modal-input:focus { border-color: #2ea6ff; }
.modal-btn { width: 100%; padding: 12px; background: #2ea6ff; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 600; cursor: pointer; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@keyframes modalFadeIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }
@media (max-width: 600px) { .chat { max-width: 100%; } .bubble { max-width: 85%; } .replies-container, .reply-toggle { margin-left: 32px; } }
</style>
</head>
<body>

<div class="chat">
    <div class="chat-header">
        <div class="chat-title">💬 Комментарии <span>online</span></div>
        <div class="post-id" id="postIdDisplay">Загрузка...</div>
    </div>
    <div class="messages" id="messages"></div>
    <div id="replyIndicator" class="reply-indicator">
        <span>📎 Ответ <strong id="replyToName"></strong></span>
        <button onclick="cancelReply()">✕</button>
    </div>
    <div class="input-area">
        <div class="input-wrapper">
            <input id="messageInput" placeholder="Написать сообщение..." disabled>
        </div>
        <button onclick="sendMessage()" disabled>Отпр</button>
    </div>
</div>
<div id="status" class="status"></div>
<div id="registerModal" class="modal">
    <div class="modal-content">
        <div class="modal-icon">👋</div>
        <div class="modal-title">Добро пожаловать!</div>
        <div class="modal-desc">Представьтесь, чтобы оставлять комментарии</div>
        <input type="text" id="usernameInput" class="modal-input" placeholder="Ваше имя" maxlength="50" autofocus>
        <button class="modal-btn" onclick="register()">Продолжить</button>
    </div>
</div>

<script>
    const urlParams = new URLSearchParams(window.location.search);
    const postId = urlParams.get('startapp') || urlParams.get('post_id') || 'general';
    document.getElementById('postIdDisplay').innerHTML = `📌 Пост: ${postId.length > 40 ? postId.substring(0, 40) + '...' : postId}`;
    
    let userId = null, userName = null, replyToId = null, replyToName = null;
    const messagesContainer = document.getElementById('messages');
    const messageInput = document.getElementById('messageInput');
    const sendBtn = document.querySelector('.input-area button');
    
    function register() {
        const name = document.getElementById('usernameInput').value.trim();
        if (!name) return;
        userName = name;
        userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
        localStorage.setItem('comment_user_id', userId);
        localStorage.setItem('comment_username', userName);
        document.getElementById('registerModal').style.display = 'none';
        messageInput.disabled = false;
        sendBtn.disabled = false;
        messageInput.focus();
        showStatus(`👋 Добро пожаловать, ${userName}!`);
        initWebSocket();
        loadMessages();
    }
    
    const savedUserId = localStorage.getItem('comment_user_id');
    const savedUserName = localStorage.getItem('comment_username');
    if (savedUserId && savedUserName) {
        userId = savedUserId; userName = savedUserName;
        document.getElementById('registerModal').style.display = 'none';
        messageInput.disabled = false; sendBtn.disabled = false;
        initWebSocket();
        loadMessages();
    }
    
    let socket = null;
    function initWebSocket() {
        socket = io();
        socket.on('connect', () => { socket.emit('join', postId); });
        socket.on('new_comment', (comment) => addCommentToTop(comment));
        socket.on('comment_updated', (comment) => updateCommentText(comment.id, comment.comment));
        socket.on('comment_deleted', (id) => removeCommentFromDOM(id));
        socket.on('disconnect', () => setTimeout(initWebSocket, 3000));
    }
    
    function getAvatarUrl(name) {
        let hash = 0;
        for (let i = 0; i < name.length; i++) hash = ((hash << 5) - hash) + name.charCodeAt(i);
        const colors = ['2ea6ff', '34c759', 'ff9500', 'ff3b30', '5856d6', '5e5ce6', 'bf5af2'];
        const color = colors[Math.abs(hash) % colors.length];
        return `https://ui-avatars.com/api/?background=${color}&color=fff&size=36&name=${encodeURIComponent(name.charAt(0))}&bold=true`;
    }
    function formatTime(iso) { return new Date(iso).toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' }); }
    function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
    function showStatus(m) { const s = document.getElementById('status'); s.textContent = m; s.classList.add('show'); setTimeout(() => s.classList.remove('show'), 2000); }
    
    async function loadMessages() {
        try {
            const res = await fetch(`/api/comments/${encodeURIComponent(postId)}`);
            const data = await res.json();
            const comments = data.comments || [];
            if (comments.length === 0) {
                messagesContainer.innerHTML = `<div class="empty-state"><div class="empty-state-icon">💬</div><div>Нет комментариев</div><div style="font-size:12px;margin-top:8px;">Будьте первым!</div></div>`;
            } else {
                renderMessages(comments);
            }
        } catch(e) { console.error(e); }
    }
    
    function renderMessages(comments) {
        messagesContainer.innerHTML = '';
        const root = comments.filter(c => !c.parent_id || c.parent_id === 0);
        const replies = comments.filter(c => c.parent_id && c.parent_id !== 0);
        root.forEach(c => {
            addMessageToDOM(c);
            const child = replies.filter(r => r.parent_id === c.id);
            if (child.length) {
                const toggle = document.createElement('div');
                toggle.className = 'reply-toggle';
                toggle.textContent = `▼ ${child.length} ответов`;
                toggle.onclick = () => {
                    const div = document.getElementById(`replies-${c.id}`);
                    if (div.style.display === 'none') {
                        div.style.display = 'block';
                        toggle.textContent = `▲ ${child.length} ответов`;
                    } else {
                        div.style.display = 'none';
                        toggle.textContent = `▼ ${child.length} ответов`;
                    }
                };
                messagesContainer.appendChild(toggle);
                const div = document.createElement('div');
                div.id = `replies-${c.id}`;
                div.className = 'replies-container';
                div.style.display = 'none';
                child.forEach(r => addReplyToDOM(div, r));
                messagesContainer.appendChild(div);
            }
        });
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
    
    function addMessageToDOM(msg) {
        const isMine = msg.user_id === userId;
        let likedBy = []; try { likedBy = JSON.parse(msg.liked_by || '[]'); } catch(e) {}
        const isLiked = likedBy.includes(userId);
        const div = document.createElement('div');
        div.className = `message ${isMine ? 'mine' : ''}`;
        div.id = `msg-${msg.id}`;
        div.innerHTML = `
            <img class="avatar" src="${getAvatarUrl(msg.username)}">
            <div class="bubble">
                <div class="name">${escapeHtml(msg.username)}</div>
                <div class="text" id="text-${msg.id}">${escapeHtml(msg.comment)}</div>
                <div class="reactions">
                    <span class="${isLiked ? 'liked' : ''}" onclick="likeMessage(${msg.id})">👍 ${msg.likes || 0}</span>
                    <span onclick="setReply(${msg.id}, '${escapeHtml(msg.username)}')">Ответить</span>
                    ${isMine ? `<span onclick="editMessage(${msg.id}, '${escapeHtml(msg.comment).replace(/'/g, "\\'")}')">✏️</span>` : ''}
                    ${isMine ? `<span onclick="deleteMessage(${msg.id})">🗑</span>` : ''}
                </div>
                <div class="time">${formatTime(msg.created_at)}</div>
            </div>
        `;
        messagesContainer.appendChild(div);
    }
    
    function addReplyToDOM(container, reply) {
        const isMine = reply.user_id === userId;
        let likedBy = []; try { likedBy = JSON.parse(reply.liked_by || '[]'); } catch(e) {}
        const isLiked = likedBy.includes(userId);
        const div = document.createElement('div');
        div.className = `message ${isMine ? 'mine' : ''}`;
        div.id = `msg-${reply.id}`;
        div.style.marginTop = '8px';
        div.innerHTML = `
            <img class="avatar" src="${getAvatarUrl(reply.username)}">
            <div class="bubble">
                <div class="name">${escapeHtml(reply.username)}</div>
                <div class="text" id="text-${reply.id}">${escapeHtml(reply.comment)}</div>
                <div class="reactions">
                    <span class="${isLiked ? 'liked' : ''}" onclick="likeMessage(${reply.id})">👍 ${reply.likes || 0}</span>
                    <span onclick="setReply(${reply.id}, '${escapeHtml(reply.username)}')">Ответить</span>
                    ${isMine ? `<span onclick="editMessage(${reply.id}, '${escapeHtml(reply.comment).replace(/'/g, "\\'")}')">✏️</span>` : ''}
                    ${isMine ? `<span onclick="deleteMessage(${reply.id})">🗑</span>` : ''}
                </div>
                <div class="time">${formatTime(reply.created_at)}</div>
            </div>
        `;
        container.appendChild(div);
    }
    
    function addCommentToTop(comment) {
        const empty = messagesContainer.querySelector('.empty-state');
        if (empty) messagesContainer.innerHTML = '';
        const isMine = comment.user_id === userId;
        let likedBy = []; try { likedBy = JSON.parse(comment.liked_by || '[]'); } catch(e) {}
        const isLiked = likedBy.includes(userId);
        const div = document.createElement('div');
        div.className = `message ${isMine ? 'mine' : ''}`;
        div.id = `msg-${comment.id}`;
        div.innerHTML = `
            <img class="avatar" src="${getAvatarUrl(comment.username)}">
            <div class="bubble">
                <div class="name">${escapeHtml(comment.username)}</div>
                <div class="text" id="text-${comment.id}">${escapeHtml(comment.comment)}</div>
                <div class="reactions">
                    <span class="${isLiked ? 'liked' : ''}" onclick="likeMessage(${comment.id})">👍 ${comment.likes || 0}</span>
                    <span onclick="setReply(${comment.id}, '${escapeHtml(comment.username)}')">Ответить</span>
                    ${isMine ? `<span onclick="editMessage(${comment.id}, '${escapeHtml(comment.comment).replace(/'/g, "\\'")}')">✏️</span>` : ''}
                    ${isMine ? `<span onclick="deleteMessage(${comment.id})">🗑</span>` : ''}
                </div>
                <div class="time">${formatTime(comment.created_at)}</div>
            </div>
        `;
        messagesContainer.appendChild(div);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
    
    function updateCommentText(id, newText) {
        const el = document.getElementById(`text-${id}`);
        if (el) el.innerHTML = escapeHtml(newText);
    }
    function removeCommentFromDOM(id) {
        const el = document.getElementById(`msg-${id}`);
        if (el) el.remove();
    }
    
    function setReply(id, name) { replyToId = id; replyToName = name; document.getElementById('replyIndicator').style.display = 'flex'; document.getElementById('replyToName').textContent = name; messageInput.focus(); }
    function cancelReply() { replyToId = null; replyToName = null; document.getElementById('replyIndicator').style.display = 'none'; }
    
    async function sendMessage() {
        if (!userName) { showStatus('Сначала представьтесь'); return; }
        const text = messageInput.value.trim();
        if (!text) { showStatus('Напишите сообщение'); return; }
        const data = { post_id: postId, user_id: userId, username: userName, comment: text };
        if (replyToId) data.parent_id = replyToId;
        sendBtn.disabled = true; sendBtn.style.opacity = '0.5';
        try {
            const res = await fetch('/api/comment', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
            if (res.ok) { messageInput.value = ''; cancelReply(); showStatus('✅ Отправлено!'); }
            else showStatus('❌ Ошибка отправки');
        } catch(e) { showStatus('❌ Ошибка соединения'); }
        finally { sendBtn.disabled = false; sendBtn.style.opacity = '1'; }
    }
    
    async function likeMessage(id) {
        if (!userId) return;
        try { await fetch(`/api/comment/${id}/like`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId }) }); loadMessages(); }
        catch(e) { console.error(e); }
    }
    async function editMessage(id, old) {
        const newText = prompt('Редактировать:', old);
        if (newText && newText.trim() && newText !== old) {
            try { await fetch(`/api/comment/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment: newText.trim(), user_id: userId }) }); loadMessages(); showStatus('✏️ Обновлено'); }
            catch(e) { showStatus('❌ Ошибка'); }
        }
    }
    async function deleteMessage(id) {
        if (!confirm('Удалить?')) return;
        try { await fetch(`/api/comment/${id}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId }) }); loadMessages(); showStatus('🗑 Удалено'); }
        catch(e) { showStatus('❌ Ошибка'); }
    }
    
    messageInput.addEventListener('keypress', e => { if (e.key === 'Enter') { e.preventDefault(); sendMessage(); } });
</script>
</body>
</html>
"""

# ========== API ДЛЯ БОТА ==========

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/comments/<post_id>')
def get_comments(post_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, parent_id, user_id, username, comment, likes, liked_by, created_at FROM comments WHERE post_id = ? ORDER BY created_at ASC", (post_id,))
    rows = c.fetchall()
    conn.close()
    comments = [{"id": r[0], "parent_id": r[1] or 0, "user_id": r[2], "username": r[3], "comment": r[4], "likes": r[5], "liked_by": r[6], "created_at": r[7]} for r in rows]
    return jsonify({"comments": comments})

@app.route('/api/post_count/<post_id>')
def get_post_count(post_id):
    """Эндпоинт для бота — возвращает количество комментариев"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM comments WHERE post_id = ?", (post_id,))
    count = c.fetchone()[0]
    conn.close()
    return jsonify({"count": count})

@app.route('/api/comment', methods=['POST'])
def add_comment():
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO comments (post_id, parent_id, user_id, username, comment, created_at, liked_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (data["post_id"], data.get("parent_id", 0), data["user_id"], data["username"], data["comment"], datetime.now().isoformat(), json.dumps([])))
    comment_id = c.lastrowid
    conn.commit()
    c.execute("SELECT id, parent_id, user_id, username, comment, likes, liked_by, created_at FROM comments WHERE id = ?", (comment_id,))
    row = c.fetchone()
    conn.close()
    new_comment = {"id": row[0], "parent_id": row[1] or 0, "user_id": row[2], "username": row[3], "comment": row[4], "likes": row[5], "liked_by": row[6], "created_at": row[7]}
    socketio.emit('new_comment', new_comment, room=data["post_id"])
    return jsonify({"ok": True})

@app.route('/api/comment/<int:id>/like', methods=['POST'])
def like_comment(id):
    data = request.get_json()
    user_id = data.get("user_id")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT liked_by, post_id FROM comments WHERE id = ?", (id,))
    row = c.fetchone()
    if row:
        liked_by = json.loads(row[0]) if row[0] else []
        post_id = row[1]
        if user_id in liked_by:
            liked_by.remove(user_id)
        else:
            liked_by.append(user_id)
        c.execute("UPDATE comments SET likes = ?, liked_by = ? WHERE id = ?", (len(liked_by), json.dumps(liked_by), id))
        conn.commit()
        c.execute("SELECT id, parent_id, user_id, username, comment, likes, liked_by, created_at FROM comments WHERE id = ?", (id,))
        updated = c.fetchone()
        updated_comment = {"id": updated[0], "parent_id": updated[1] or 0, "user_id": updated[2], "username": updated[3], "comment": updated[4], "likes": updated[5], "liked_by": updated[6], "created_at": updated[7]}
        socketio.emit('comment_updated', updated_comment, room=post_id)
    conn.close()
    return jsonify({"ok": True})

@app.route('/api/comment/<int:id>', methods=['PUT'])
def edit_comment(id):
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT post_id FROM comments WHERE id = ? AND user_id = ?", (id, data["user_id"]))
    row = c.fetchone()
    if row:
        post_id = row[0]
        c.execute("UPDATE comments SET comment = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                  (data["comment"], datetime.now().isoformat(), id, data["user_id"]))
        conn.commit()
        c.execute("SELECT id, parent_id, user_id, username, comment, likes, liked_by, created_at FROM comments WHERE id = ?", (id,))
        updated = c.fetchone()
        updated_comment = {"id": updated[0], "parent_id": updated[1] or 0, "user_id": updated[2], "username": updated[3], "comment": updated[4], "likes": updated[5], "liked_by": updated[6], "created_at": updated[7]}
        socketio.emit('comment_updated', updated_comment, room=post_id)
    conn.close()
    return jsonify({"ok": True})

@app.route('/api/comment/<int:id>', methods=['DELETE'])
def delete_comment(id):
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT post_id FROM comments WHERE id = ? AND user_id = ?", (id, data["user_id"]))
    row = c.fetchone()
    if row:
        post_id = row[0]
        c.execute("DELETE FROM comments WHERE id = ? AND user_id = ?", (id, data["user_id"]))
        conn.commit()
        socketio.emit('comment_deleted', id, room=post_id)
    conn.close()
    return jsonify({"ok": True})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@socketio.on('join')
def on_join(data):
    join_room(data)
    print(f"🔌 Клиент подключился к комнате {data}")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8000, debug=True)
