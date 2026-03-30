from flask import Flask, request, jsonify, render_template_string
from flask_socketio import SocketIO, emit, join_room
import sqlite3
from datetime import datetime
import json
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

DB_PATH = "comments.db"

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

init_db()

HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>Комментарии</title>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #0e0e10;
            color: #e4e6eb;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        .chat-header {
            background: #1e1e22;
            padding: 12px 16px;
            border-bottom: 1px solid #2a2a2e;
            text-align: center;
            flex-shrink: 0;
        }
        
        .chat-title {
            font-weight: 600;
            font-size: 17px;
        }
        
        .post-id {
            font-size: 10px;
            color: #8e8e93;
            margin-top: 4px;
            background: #2c2c30;
            padding: 4px 10px;
            border-radius: 12px;
            display: inline-block;
            word-break: break-all;
            max-width: 90%;
        }
        
        .messages-area {
            flex: 1;
            overflow-y: auto;
            padding: 12px 16px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .message {
            display: flex;
            gap: 10px;
            max-width: 100%;
            animation: fadeIn 0.2s ease;
        }
        
        .message-avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 14px;
            flex-shrink: 0;
            background: #0a84ff;
        }
        
        .message-content {
            flex: 1;
            background: #1e1e22;
            border-radius: 18px;
            padding: 8px 12px;
            border: 1px solid #2a2a2e;
        }
        
        .message-header {
            display: flex;
            align-items: baseline;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 4px;
        }
        
        .message-name {
            font-weight: 600;
            font-size: 14px;
        }
        
        .message-badge {
            font-size: 10px;
            background: #2c2c30;
            color: #8e8e93;
            padding: 2px 6px;
            border-radius: 10px;
        }
        
        .message-time {
            font-size: 10px;
            color: #8e8e93;
        }
        
        .message-text {
            font-size: 14px;
            line-height: 1.4;
            word-break: break-word;
            margin: 4px 0;
        }
        
        .message-actions {
            display: flex;
            gap: 12px;
            margin-top: 6px;
            font-size: 12px;
        }
        
        .message-actions button {
            background: none;
            border: none;
            color: #8e8e93;
            cursor: pointer;
            font-size: 12px;
            padding: 2px 0;
        }
        
        .like-btn.liked {
            color: #ff375f;
        }
        
        .reply-btn {
            color: #0a84ff;
        }
        
        .reply-toggle {
            font-size: 11px;
            color: #8e8e93;
            cursor: pointer;
            margin-left: 46px;
            margin-top: 4px;
            display: inline-block;
        }
        
        .replies-container {
            margin-left: 46px;
            margin-top: 8px;
            display: none;
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #8e8e93;
        }
        
        .input-bar {
            background: #1e1e22;
            border-top: 1px solid #2a2a2e;
            padding: 8px 12px;
            display: flex;
            align-items: flex-end;
            gap: 8px;
            flex-shrink: 0;
        }
        
        .input-wrapper {
            flex: 1;
            background: #2c2c30;
            border-radius: 24px;
            padding: 8px 16px;
        }
        
        .input-wrapper textarea {
            width: 100%;
            background: none;
            border: none;
            color: #e4e6eb;
            font-size: 15px;
            font-family: inherit;
            resize: none;
            outline: none;
            min-height: 24px;
            max-height: 100px;
        }
        
        .send-btn {
            background: #0a84ff;
            border: none;
            width: 36px;
            height: 36px;
            border-radius: 36px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            flex-shrink: 0;
        }
        
        .send-btn svg {
            width: 18px;
            height: 18px;
            fill: white;
        }
        
        .reply-indicator {
            background: #2c2c30;
            padding: 6px 12px;
            border-radius: 20px;
            margin: 0 12px 4px 12px;
            font-size: 12px;
            display: none;
            align-items: center;
            justify-content: space-between;
        }
        
        .reply-indicator button {
            background: none;
            border: none;
            color: #ff453a;
            cursor: pointer;
        }
        
        .status {
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            background: #2c2c30;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            opacity: 0;
            transition: opacity 0.2s;
            pointer-events: none;
            z-index: 200;
        }
        
        .status.show {
            opacity: 1;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(5px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body>
    <div class="chat-header">
        <div class="chat-title">💬 Комментарии</div>
        <div class="post-id" id="postIdDisplay"></div>
    </div>
    
    <div id="messagesContainer" class="messages-area">
        <div class="empty-state">Загрузка...</div>
    </div>
    
    <div id="replyIndicator" class="reply-indicator">
        <span>📎 Ответ <strong id="replyToName"></strong></span>
        <button onclick="cancelReply()">✕</button>
    </div>
    
    <div class="input-bar">
        <div class="input-wrapper">
            <textarea id="messageInput" placeholder="Сообщение..." rows="1"></textarea>
        </div>
        <button class="send-btn" onclick="sendMessage()">
            <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
    </div>
    
    <div id="status" class="status"></div>

    <script>
        // ========== ПОЛУЧАЕМ ID ПОСТА ==========
        const urlParams = new URLSearchParams(window.location.search);
        let postId = urlParams.get('startapp') || urlParams.get('post') || 'general';
        document.getElementById('postIdDisplay').innerHTML = postId.length > 50 ? postId.substring(0, 47) + '...' : postId;
        
        // ========== ПОЛУЧАЕМ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ИЗ MAX ==========
        let userId = null;
        let userName = null;
        
        // Пытаемся получить из MAX WebApp
        try {
            if (window.Maxi && window.Maxi.initDataUnsafe && window.Maxi.initDataUnsafe.user) {
                const user = window.Maxi.initDataUnsafe.user;
                userId = user.id.toString();
                userName = user.first_name + (user.last_name ? ' ' + user.last_name : '');
                console.log('Данные из MAX:', userId, userName);
            } else if (window.TelegramWebApp && window.TelegramWebApp.initDataUnsafe && window.TelegramWebApp.initDataUnsafe.user) {
                const user = window.TelegramWebApp.initDataUnsafe.user;
                userId = user.id.toString();
                userName = user.first_name + (user.last_name ? ' ' + user.last_name : '');
                console.log('Данные из Telegram:', userId, userName);
            }
        } catch(e) {
            console.log('MAX API не доступен:', e);
        }
        
        // Если не получили из MAX, используем localStorage
        if (!userId) {
            userId = localStorage.getItem('comment_user_id');
            if (!userId) {
                userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
                localStorage.setItem('comment_user_id', userId);
            }
        }
        
        if (!userName) {
            userName = localStorage.getItem('comment_username');
            if (!userName) {
                // Пробуем получить имя из URL
                const urlName = urlParams.get('username');
                if (urlName) {
                    userName = decodeURIComponent(urlName);
                } else {
                    userName = 'Гость';
                }
                localStorage.setItem('comment_username', userName);
            }
        }
        
        // Если имя "Гость" и есть ID, можно сгенерировать красивое имя
        if (userName === 'Гость' && userId) {
            userName = 'Пользователь_' + userId.slice(-4);
            localStorage.setItem('comment_username', userName);
        }
        
        console.log('Пользователь:', userId, userName);
        
        let replyToId = null;
        let replyToName = null;
        
        const messageInput = document.getElementById('messageInput');
        
        messageInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 100) + 'px';
        });
        
        messageInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        
        // ========== WEBSOCKET ==========
        const socket = io();
        socket.emit('join', postId);
        
        socket.on('new_comment', function(comment) {
            console.log('Новый комментарий:', comment);
            addCommentToTop(comment);
        });
        
        socket.on('comment_updated', function(comment) {
            console.log('Комментарий обновлён:', comment);
            updateCommentInDOM(comment);
        });
        
        socket.on('comment_deleted', function(commentId) {
            console.log('Комментарий удалён:', commentId);
            removeCommentFromDOM(commentId);
        });
        
        function getAvatarColor(name) {
            let hash = 0;
            for (let i = 0; i < name.length; i++) {
                hash = ((hash << 5) - hash) + name.charCodeAt(i);
                hash |= 0;
            }
            const colors = ['#0a84ff', '#30d158', '#ff9f0a', '#ff375f', '#5e5ce6', '#64d2ff', '#bf5af2'];
            return colors[Math.abs(hash) % colors.length];
        }
        
        // ========== ЗАГРУЗКА КОММЕНТАРИЕВ ==========
        async function loadMessages() {
            try {
                const response = await fetch(`/api/comments/${encodeURIComponent(postId)}`);
                const data = await response.json();
                const container = document.getElementById('messagesContainer');
                
                if (data.comments && data.comments.length > 0) {
                    container.innerHTML = '';
                    const rootComments = data.comments.filter(c => c.parent_id === 0);
                    const replies = data.comments.filter(c => c.parent_id !== 0);
                    
                    rootComments.forEach(c => {
                        addMessageToDOM(c);
                        const childReplies = replies.filter(r => r.parent_id === c.id);
                        if (childReplies.length > 0) {
                            const toggle = document.createElement('div');
                            toggle.className = 'reply-toggle';
                            toggle.textContent = `▼ ${childReplies.length} ответов`;
                            toggle.onclick = () => {
                                const repliesDiv = document.getElementById(`replies-${c.id}`);
                                if (repliesDiv.style.display === 'none') {
                                    repliesDiv.style.display = 'block';
                                    toggle.textContent = `▲ ${childReplies.length} ответов`;
                                } else {
                                    repliesDiv.style.display = 'none';
                                    toggle.textContent = `▼ ${childReplies.length} ответов`;
                                }
                            };
                            container.appendChild(toggle);
                            
                            const repliesDiv = document.createElement('div');
                            repliesDiv.id = `replies-${c.id}`;
                            repliesDiv.className = 'replies-container';
                            repliesDiv.style.display = 'none';
                            childReplies.forEach(r => addReplyToDOM(repliesDiv, r));
                            container.appendChild(repliesDiv);
                        }
                    });
                } else {
                    container.innerHTML = `<div class="empty-state">💬 Нет сообщений<br><span style="font-size:12px">Напишите первое сообщение</span></div>`;
                }
                container.scrollTop = container.scrollHeight;
            } catch (error) {
                console.error(error);
                document.getElementById('messagesContainer').innerHTML = '<div class="empty-state">⚠️ Ошибка загрузки</div>';
            }
        }
        
        function addMessageToDOM(comment) {
            const container = document.getElementById('messagesContainer');
            const time = new Date(comment.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
            const avatarColor = getAvatarColor(comment.username);
            const letter = (comment.username.charAt(0) || '?').toUpperCase();
            const isMine = comment.user_id === userId;
            let likedBy = [];
            try { likedBy = JSON.parse(comment.liked_by || '[]'); } catch(e) {}
            const isLiked = likedBy.includes(userId);
            
            const div = document.createElement('div');
            div.className = 'message';
            div.id = `msg-${comment.id}`;
            div.innerHTML = `
                <div class="message-avatar" style="background: ${avatarColor}">${escapeHtml(letter)}</div>
                <div class="message-content">
                    <div class="message-header">
                        <span class="message-name">${escapeHtml(comment.username)}</span>
                        ${isMine ? '<span class="message-badge">Вы</span>' : ''}
                        <span class="message-time">${time}</span>
                    </div>
                    <div class="message-text" id="text-${comment.id}">${escapeHtml(comment.comment)}</div>
                    <div class="message-actions">
                        <button class="like-btn ${isLiked ? 'liked' : ''}" onclick="likeComment(${comment.id})">❤️ ${comment.likes || 0}</button>
                        <button class="reply-btn" onclick="setReply(${comment.id}, '${escapeHtml(comment.username)}')">💬 Ответить</button>
                        ${isMine ? `<button onclick="editComment(${comment.id}, '${escapeHtml(comment.comment).replace(/'/g, "\\'")}')">✏️</button>` : ''}
                        ${isMine ? `<button onclick="deleteComment(${comment.id})">🗑</button>` : ''}
                    </div>
                </div>
            `;
            container.appendChild(div);
        }
        
        function addCommentToTop(comment) {
            const container = document.getElementById('messagesContainer');
            const time = new Date(comment.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
            const avatarColor = getAvatarColor(comment.username);
            const letter = (comment.username.charAt(0) || '?').toUpperCase();
            const isMine = comment.user_id === userId;
            
            const div = document.createElement('div');
            div.className = 'message';
            div.id = `msg-${comment.id}`;
            div.innerHTML = `
                <div class="message-avatar" style="background: ${avatarColor}">${escapeHtml(letter)}</div>
                <div class="message-content">
                    <div class="message-header">
                        <span class="message-name">${escapeHtml(comment.username)}</span>
                        ${isMine ? '<span class="message-badge">Вы</span>' : ''}
                        <span class="message-time">${time}</span>
                    </div>
                    <div class="message-text" id="text-${comment.id}">${escapeHtml(comment.comment)}</div>
                    <div class="message-actions">
                        <button class="like-btn" onclick="likeComment(${comment.id})">❤️ 0</button>
                        <button class="reply-btn" onclick="setReply(${comment.id}, '${escapeHtml(comment.username)}')">💬 Ответить</button>
                        ${isMine ? `<button onclick="editComment(${comment.id}, '${escapeHtml(comment.comment).replace(/'/g, "\\'")}')">✏️</button>` : ''}
                        ${isMine ? `<button onclick="deleteComment(${comment.id})">🗑</button>` : ''}
                    </div>
                </div>
            `;
            
            const emptyState = container.querySelector('.empty-state');
            if (emptyState) {
                container.innerHTML = '';
            }
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        }
        
        function updateCommentInDOM(comment) {
            const textDiv = document.getElementById(`text-${comment.id}`);
            if (textDiv) {
                textDiv.innerHTML = escapeHtml(comment.comment);
            }
        }
        
        function removeCommentFromDOM(commentId) {
            const msgDiv = document.getElementById(`msg-${commentId}`);
            if (msgDiv) {
                msgDiv.remove();
            }
        }
        
        function addReplyToDOM(container, reply) {
            const time = new Date(reply.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
            const avatarColor = getAvatarColor(reply.username);
            const letter = (reply.username.charAt(0) || '?').toUpperCase();
            const isMine = reply.user_id === userId;
            let likedBy = [];
            try { likedBy = JSON.parse(reply.liked_by || '[]'); } catch(e) {}
            const isLiked = likedBy.includes(userId);
            
            const div = document.createElement('div');
            div.className = 'message';
            div.id = `msg-${reply.id}`;
            div.style.marginTop = '8px';
            div.innerHTML = `
                <div class="message-avatar" style="background: ${avatarColor}">${escapeHtml(letter)}</div>
                <div class="message-content">
                    <div class="message-header">
                        <span class="message-name">${escapeHtml(reply.username)}</span>
                        ${isMine ? '<span class="message-badge">Вы</span>' : ''}
                        <span class="message-time">${time}</span>
                    </div>
                    <div class="message-text" id="text-${reply.id}">${escapeHtml(reply.comment)}</div>
                    <div class="message-actions">
                        <button class="like-btn ${isLiked ? 'liked' : ''}" onclick="likeComment(${reply.id})">❤️ ${reply.likes || 0}</button>
                        <button class="reply-btn" onclick="setReply(${reply.id}, '${escapeHtml(reply.username)}')">💬 Ответить</button>
                        ${isMine ? `<button onclick="editComment(${reply.id}, '${escapeHtml(reply.comment).replace(/'/g, "\\'")}')">✏️</button>` : ''}
                        ${isMine ? `<button onclick="deleteComment(${reply.id})">🗑</button>` : ''}
                    </div>
                </div>
            `;
            container.appendChild(div);
        }
        
        function setReply(id, name) {
            replyToId = id;
            replyToName = name;
            document.getElementById('replyIndicator').style.display = 'flex';
            document.getElementById('replyToName').textContent = name;
            messageInput.focus();
        }
        
        function cancelReply() {
            replyToId = null;
            replyToName = null;
            document.getElementById('replyIndicator').style.display = 'none';
        }
        
        async function sendMessage() {
            const text = messageInput.value.trim();
            if (!text) {
                showStatus('Напишите сообщение', 'error');
                return;
            }
            
            const data = {
                post_id: postId,
                user_id: userId,
                username: userName,
                comment: text
            };
            if (replyToId) data.parent_id = replyToId;
            
            try {
                const response = await fetch('/api/comment', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    messageInput.value = '';
                    messageInput.style.height = 'auto';
                    cancelReply();
                    showStatus('✅ Отправлено!', 'success');
                } else {
                    showStatus('❌ Ошибка', 'error');
                }
            } catch (error) {
                showStatus('❌ Ошибка соединения', 'error');
            }
        }
        
        async function likeComment(id) {
            try {
                const response = await fetch(`/api/comment/${id}/like`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId })
                });
                if (response.ok) {
                    loadMessages();
                }
            } catch(e) { console.error(e); }
        }
        
        async function editComment(id, oldText) {
            const newText = prompt('Редактировать сообщение:', oldText);
            if (newText && newText.trim() && newText !== oldText) {
                try {
                    const response = await fetch(`/api/comment/${id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ comment: newText.trim(), user_id: userId })
                    });
                    if (response.ok) {
                        showStatus('✏️ Сообщение обновлено', 'success');
                    }
                } catch(e) { showStatus('❌ Ошибка', 'error'); }
            }
        }
        
        async function deleteComment(id) {
            if (!confirm('Удалить сообщение?')) return;
            try {
                const response = await fetch(`/api/comment/${id}`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId })
                });
                if (response.ok) {
                    showStatus('🗑 Сообщение удалено', 'success');
                }
            } catch(e) { showStatus('❌ Ошибка', 'error'); }
        }
        
        function showStatus(msg, type) {
            const div = document.getElementById('status');
            div.textContent = msg;
            div.classList.add('show');
            setTimeout(() => div.classList.remove('show'), 2000);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        loadMessages();
    </script>
</body>
</html>
"""

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

@app.route('/api/comment', methods=['POST'])
def add_comment():
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO comments (post_id, parent_id, user_id, username, comment, created_at, liked_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (data["post_id"], data.get("parent_id", 0), data["user_id"], data["username"], data["comment"], datetime.now().isoformat(), json.dumps([])))
    conn.commit()
    
    comment_id = c.lastrowid
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
        conn.close()
        
        updated_comment = {"id": updated[0], "parent_id": updated[1] or 0, "user_id": updated[2], "username": updated[3], "comment": updated[4], "likes": updated[5], "liked_by": updated[6], "created_at": updated[7]}
        
        socketio.emit('comment_updated', updated_comment, room=post_id)
        
        return jsonify({"ok": True})
    conn.close()
    return jsonify({"ok": False})

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
        conn.close()
        
        updated_comment = {"id": updated[0], "parent_id": updated[1] or 0, "user_id": updated[2], "username": updated[3], "comment": updated[4], "likes": updated[5], "liked_by": updated[6], "created_at": updated[7]}
        
        socketio.emit('comment_updated', updated_comment, room=post_id)
        
        return jsonify({"ok": True})
    conn.close()
    return jsonify({"ok": False})

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
        conn.close()
        
        socketio.emit('comment_deleted', id, room=post_id)
        
        return jsonify({"ok": True})
    conn.close()
    return jsonify({"ok": False})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@socketio.on('join')
def on_join(data):
    room = data
    join_room(room)
    print(f"Клиент подключился к комнате {room}")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8000, debug=True)
