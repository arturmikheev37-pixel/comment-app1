from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime
import hashlib
import re

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
        post_id TEXT NOT NULL,
        parent_id INTEGER DEFAULT 0,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        avatar_color TEXT,
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

# ---------------- HTML шаблон ----------------
HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>Комментарии</title>
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
            padding: 12px;
            padding-bottom: 80px;
        }
        
        .container {
            max-width: 700px;
            margin: 0 auto;
        }
        
        /* Шапка поста */
        .post-header {
            background: #1e1e22;
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 20px;
            border: 1px solid #2a2a2e;
        }
        
        .post-title {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .post-id {
            font-size: 11px;
            color: #8e8e93;
            word-break: break-all;
            background: #2c2c30;
            padding: 6px 12px;
            border-radius: 20px;
            display: inline-block;
        }
        
        /* Форма комментария */
        .comment-form {
            background: #1e1e22;
            border-radius: 20px;
            padding: 12px;
            margin-bottom: 20px;
            border: 1px solid #2a2a2e;
        }
        
        .reply-indicator {
            background: #2c2c30;
            padding: 8px 12px;
            border-radius: 12px;
            margin-bottom: 10px;
            font-size: 13px;
            color: #8e8e93;
            display: none;
            align-items: center;
            justify-content: space-between;
        }
        
        .reply-indicator button {
            background: none;
            border: none;
            color: #ff453a;
            font-size: 14px;
            cursor: pointer;
        }
        
        .form-row {
            display: flex;
            gap: 10px;
            align-items: flex-end;
        }
        
        .form-group {
            flex: 1;
        }
        
        .form-group input {
            width: 100%;
            padding: 12px 14px;
            background: #2c2c30;
            border: 1px solid #3a3a3e;
            border-radius: 24px;
            font-size: 15px;
            color: #e4e6eb;
            transition: all 0.2s;
        }
        
        .form-group input:focus {
            outline: none;
            border-color: #0a84ff;
            background: #1e1e22;
        }
        
        .form-group textarea {
            width: 100%;
            padding: 12px 14px;
            background: #2c2c30;
            border: 1px solid #3a3a3e;
            border-radius: 20px;
            font-size: 15px;
            font-family: inherit;
            resize: none;
            color: #e4e6eb;
            min-height: 44px;
            max-height: 120px;
        }
        
        .form-group textarea:focus {
            outline: none;
            border-color: #0a84ff;
            background: #1e1e22;
        }
        
        .send-btn {
            background: #0a84ff;
            border: none;
            width: 44px;
            height: 44px;
            border-radius: 44px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: opacity 0.2s;
            flex-shrink: 0;
        }
        
        .send-btn:active {
            opacity: 0.7;
        }
        
        .send-btn svg {
            width: 22px;
            height: 22px;
            fill: white;
        }
        
        /* Заголовок списка */
        .comments-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding: 0 4px;
        }
        
        .comments-count {
            font-size: 15px;
            font-weight: 500;
            color: #8e8e93;
        }
        
        .refresh-btn {
            background: none;
            border: none;
            color: #0a84ff;
            font-size: 13px;
            padding: 6px 12px;
            cursor: pointer;
            border-radius: 20px;
        }
        
        /* Список комментариев */
        .comments-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        .comment-card {
            background: #1e1e22;
            border-radius: 16px;
            padding: 12px;
            border: 1px solid #2a2a2e;
            transition: background 0.2s;
        }
        
        .comment-reply {
            margin-left: 44px;
            margin-top: 12px;
            padding-left: 12px;
            border-left: 2px solid #3a3a3e;
        }
        
        .comment-header {
            display: flex;
            align-items: flex-start;
            gap: 12px;
        }
        
        .comment-avatar {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 16px;
            flex-shrink: 0;
            background: #0a84ff;
        }
        
        .comment-content {
            flex: 1;
        }
        
        .comment-name-row {
            display: flex;
            align-items: baseline;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 4px;
        }
        
        .comment-name {
            font-weight: 600;
            font-size: 14px;
        }
        
        .comment-badge {
            font-size: 11px;
            background: #2c2c30;
            color: #8e8e93;
            padding: 2px 8px;
            border-radius: 12px;
        }
        
        .comment-time {
            font-size: 11px;
            color: #8e8e93;
        }
        
        .comment-text {
            font-size: 14px;
            line-height: 1.45;
            margin: 6px 0 8px 0;
            word-break: break-word;
        }
        
        .comment-actions {
            display: flex;
            gap: 16px;
            align-items: center;
            margin-top: 4px;
        }
        
        .comment-actions button {
            background: none;
            border: none;
            font-size: 12px;
            color: #8e8e93;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 16px;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 4px;
        }
        
        .comment-actions button:active {
            background: #2c2c30;
        }
        
        .like-btn.liked {
            color: #ff375f;
        }
        
        .reply-btn {
            color: #0a84ff;
        }
        
        .edit-btn, .delete-btn {
            color: #8e8e93;
        }
        
        .delete-btn:hover {
            color: #ff453a;
        }
        
        .reply-count {
            font-size: 12px;
            color: #8e8e93;
            margin-left: 44px;
            margin-top: 8px;
            cursor: pointer;
            display: inline-block;
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #8e8e93;
        }
        
        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }
        
        .status {
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            background: #2c2c30;
            color: white;
            padding: 8px 16px;
            border-radius: 40px;
            font-size: 13px;
            z-index: 200;
            opacity: 0;
            transition: opacity 0.2s;
            pointer-events: none;
        }
        
        .status.show {
            opacity: 1;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #8e8e93;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(5px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .comment-card {
            animation: fadeIn 0.2s ease;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="post-header">
            <div class="post-title">💬 Обсуждение</div>
            <div class="post-id" id="postIdDisplay"></div>
        </div>
        
        <div class="comment-form">
            <div class="reply-indicator" id="replyIndicator">
                <span>📎 Ответ для <strong id="replyToName"></strong></span>
                <button onclick="cancelReply()">✕</button>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <input type="text" id="username" placeholder="Ваше имя" maxlength="50">
                </div>
                <div class="form-group">
                    <textarea id="commentText" placeholder="Написать комментарий..." rows="1" maxlength="500"></textarea>
                </div>
                <button class="send-btn" onclick="sendComment()">
                    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                    </svg>
                </button>
            </div>
        </div>
        
        <div class="comments-header">
            <span class="comments-count" id="commentsCount">Комментарии (0)</span>
            <button class="refresh-btn" onclick="loadComments()">🔄 Обновить</button>
        </div>
        
        <div id="commentsList" class="comments-list">
            <div class="loading">Загрузка комментариев...</div>
        </div>
    </div>
    
    <div id="status" class="status"></div>

    <script>
        // Получаем post_id из URL
        const urlParams = new URLSearchParams(window.location.search);
        let postId = urlParams.get('startapp') || urlParams.get('post') || 'general';
        
        document.getElementById('postIdDisplay').innerHTML = `📌 Пост: ${postId.length > 40 ? postId.substring(0, 40) + '...' : postId}`;
        
        // Данные пользователя
        let userId = localStorage.getItem('comment_user_id');
        if (!userId) {
            userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 8);
            localStorage.setItem('comment_user_id', userId);
        }
        
        let userName = localStorage.getItem('comment_username') || '';
        if (userName) {
            document.getElementById('username').value = userName;
        }
        
        // Сохраняем имя
        document.getElementById('username').addEventListener('input', function() {
            userName = this.value.trim();
            localStorage.setItem('comment_username', userName);
        });
        
        // Переменные для ответа
        let replyToId = null;
        let replyToName = null;
        
        // Авто-расширение textarea
        const commentText = document.getElementById('commentText');
        commentText.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
        });
        
        // Отправка по Ctrl+Enter
        commentText.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                sendComment();
            }
        });
        
        // Функция для генерации цвета аватарки
        function getAvatarColor(name) {
            let hash = 0;
            for (let i = 0; i < name.length; i++) {
                hash = ((hash << 5) - hash) + name.charCodeAt(i);
                hash |= 0;
            }
            const colors = ['#0a84ff', '#30d158', '#ff9f0a', '#ff375f', '#5e5ce6', '#64d2ff', '#bf5af2'];
            return colors[Math.abs(hash) % colors.length];
        }
        
        // Загрузка комментариев
        async function loadComments() {
            try {
                const response = await fetch(`/api/comments/${encodeURIComponent(postId)}`);
                const data = await response.json();
                const container = document.getElementById('commentsList');
                
                if (data.comments && data.comments.length > 0) {
                    container.innerHTML = '';
                    // Группируем по parent_id
                    const commentsMap = new Map();
                    const rootComments = [];
                    
                    data.comments.forEach(c => {
                        c.replies = [];
                        commentsMap.set(c.id, c);
                        if (c.parent_id === 0) {
                            rootComments.push(c);
                        }
                    });
                    
                    data.comments.forEach(c => {
                        if (c.parent_id !== 0 && commentsMap.has(c.parent_id)) {
                            commentsMap.get(c.parent_id).replies.push(c);
                        }
                    });
                    
                    rootComments.forEach(c => {
                        addCommentToDOM(c);
                        if (c.replies && c.replies.length > 0) {
                            c.replies.forEach(reply => addReplyToDOM(reply, c.id));
                        }
                    });
                } else {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">💬</div>
                            <div>Пока нет комментариев</div>
                            <div style="font-size: 12px; margin-top: 8px;">Будьте первым!</div>
                        </div>
                    `;
                }
                document.getElementById('commentsCount').textContent = `Комментарии (${data.comments?.length || 0})`;
            } catch (error) {
                console.error('Ошибка:', error);
                document.getElementById('commentsList').innerHTML = '<div class="empty-state">⚠️ Ошибка загрузки</div>';
            }
        }
        
        function addCommentToDOM(comment) {
            const container = document.getElementById('commentsList');
            const time = new Date(comment.created_at).toLocaleString('ru-RU');
            const avatarColor = comment.avatar_color || getAvatarColor(comment.username);
            const letter = (comment.username.charAt(0) || '?').toUpperCase();
            const isMine = comment.user_id === userId;
            const isLiked = comment.liked_by ? JSON.parse(comment.liked_by).includes(userId) : false;
            
            const div = document.createElement('div');
            div.className = 'comment-card';
            div.id = `comment-${comment.id}`;
            div.innerHTML = `
                <div class="comment-header">
                    <div class="comment-avatar" style="background: ${avatarColor}">${escapeHtml(letter)}</div>
                    <div class="comment-content">
                        <div class="comment-name-row">
                            <span class="comment-name">${escapeHtml(comment.username)}</span>
                            ${isMine ? '<span class="comment-badge">Вы</span>' : ''}
                            <span class="comment-time">${time}</span>
                        </div>
                        <div class="comment-text">${escapeHtml(comment.comment)}</div>
                        <div class="comment-actions">
                            <button class="like-btn ${isLiked ? 'liked' : ''}" onclick="likeComment(${comment.id})">❤️ ${comment.likes || 0}</button>
                            <button class="reply-btn" onclick="setReply(${comment.id}, '${escapeHtml(comment.username)}')">💬 Ответить</button>
                            ${isMine ? `<button class="edit-btn" onclick="editComment(${comment.id}, '${escapeHtml(comment.comment).replace(/'/g, "\\'")}')">✏️</button>` : ''}
                            ${isMine ? `<button class="delete-btn" onclick="deleteComment(${comment.id})">🗑</button>` : ''}
                        </div>
                    </div>
                </div>
            `;
            container.appendChild(div);
        }
        
        function addReplyToDOM(reply, parentId) {
            const parentDiv = document.getElementById(`comment-${parentId}`);
            if (!parentDiv) return;
            
            let repliesContainer = parentDiv.querySelector('.replies-container');
            if (!repliesContainer) {
                repliesContainer = document.createElement('div');
                repliesContainer.className = 'comment-reply replies-container';
                parentDiv.appendChild(repliesContainer);
                
                // Добавляем счетчик ответов
                const replyCountSpan = document.createElement('span');
                replyCountSpan.className = 'reply-count';
                replyCountSpan.textContent = '▼ показать ответы';
                replyCountSpan.onclick = () => toggleReplies(repliesContainer, replyCountSpan);
                parentDiv.appendChild(replyCountSpan);
            }
            
            const time = new Date(reply.created_at).toLocaleString('ru-RU');
            const avatarColor = reply.avatar_color || getAvatarColor(reply.username);
            const letter = (reply.username.charAt(0) || '?').toUpperCase();
            const isMine = reply.user_id === userId;
            const isLiked = reply.liked_by ? JSON.parse(reply.liked_by).includes(userId) : false;
            
            const replyDiv = document.createElement('div');
            replyDiv.className = 'comment-card';
            replyDiv.id = `comment-${reply.id}`;
            replyDiv.innerHTML = `
                <div class="comment-header">
                    <div class="comment-avatar" style="background: ${avatarColor}">${escapeHtml(letter)}</div>
                    <div class="comment-content">
                        <div class="comment-name-row">
                            <span class="comment-name">${escapeHtml(reply.username)}</span>
                            ${isMine ? '<span class="comment-badge">Вы</span>' : ''}
                            <span class="comment-time">${time}</span>
                        </div>
                        <div class="comment-text">${escapeHtml(reply.comment)}</div>
                        <div class="comment-actions">
                            <button class="like-btn ${isLiked ? 'liked' : ''}" onclick="likeComment(${reply.id})">❤️ ${reply.likes || 0}</button>
                            <button class="reply-btn" onclick="setReply(${reply.id}, '${escapeHtml(reply.username)}')">💬 Ответить</button>
                            ${isMine ? `<button class="edit-btn" onclick="editComment(${reply.id}, '${escapeHtml(reply.comment).replace(/'/g, "\\'")}')">✏️</button>` : ''}
                            ${isMine ? `<button class="delete-btn" onclick="deleteComment(${reply.id})">🗑</button>` : ''}
                        </div>
                    </div>
                </div>
            `;
            repliesContainer.appendChild(replyDiv);
        }
        
        function toggleReplies(container, btn) {
            if (container.style.display === 'none') {
                container.style.display = 'block';
                btn.textContent = '▲ скрыть ответы';
            } else {
                container.style.display = 'none';
                btn.textContent = '▼ показать ответы';
            }
        }
        
        function setReply(id, name) {
            replyToId = id;
            replyToName = name;
            document.getElementById('replyIndicator').style.display = 'flex';
            document.getElementById('replyToName').textContent = name;
            document.getElementById('commentText').focus();
        }
        
        function cancelReply() {
            replyToId = null;
            replyToName = null;
            document.getElementById('replyIndicator').style.display = 'none';
        }
        
        async function sendComment() {
            const username = userName.trim();
            const comment = commentText.value.trim();
            
            if (!username) {
                showStatus('❌ Введите ваше имя', 'error');
                document.getElementById('username').focus();
                return;
            }
            if (!comment) {
                showStatus('❌ Введите комментарий', 'error');
                commentText.focus();
                return;
            }
            
            const data = {
                post_id: postId,
                user_id: userId,
                username: username,
                comment: comment
            };
            
            if (replyToId) {
                data.parent_id = replyToId;
            }
            
            try {
                const response = await fetch('/api/comment', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    showStatus('✅ Комментарий отправлен!', 'success');
                    commentText.value = '';
                    commentText.style.height = 'auto';
                    cancelReply();
                    await loadComments();
                    setTimeout(() => {
                        if (window.Maxi && window.Maxi.close) window.Maxi.close();
                    }, 1500);
                } else {
                    showStatus('❌ Ошибка отправки', 'error');
                }
            } catch (error) {
                showStatus('❌ Ошибка соединения', 'error');
            }
        }
        
        async function likeComment(commentId) {
            try {
                const response = await fetch(`/api/comment/${commentId}/like`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId })
                });
                if (response.ok) {
                    loadComments();
                }
            } catch (error) {
                console.error('Ошибка лайка:', error);
            }
        }
        
        async function editComment(commentId, oldText) {
            const newText = prompt('Редактировать комментарий:', oldText);
            if (newText && newText.trim() !== '') {
                try {
                    const response = await fetch(`/api/comment/${commentId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ comment: newText.trim(), user_id: userId })
                    });
                    if (response.ok) {
                        loadComments();
                        showStatus('✏️ Комментарий обновлен', 'success');
                    }
                } catch (error) {
                    showStatus('❌ Ошибка редактирования', 'error');
                }
            }
        }
        
        async function deleteComment(commentId) {
            if (!confirm('Удалить комментарий?')) return;
            try {
                const response = await fetch(`/api/comment/${commentId}`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId })
                });
                if (response.ok) {
                    loadComments();
                    showStatus('🗑 Комментарий удален', 'success');
                }
            } catch (error) {
                showStatus('❌ Ошибка удаления', 'error');
            }
        }
        
        function showStatus(message, type) {
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.classList.add('show');
            setTimeout(() => {
                statusDiv.classList.remove('show');
            }, 2000);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Запуск
        loadComments();
        setInterval(loadComments, 5000);
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
    c.execute("""
        SELECT id, parent_id, user_id, username, comment, likes, liked_by, created_at, updated_at 
        FROM comments 
        WHERE post_id = ? 
        ORDER BY created_at ASC
    """, (post_id,))
    rows = c.fetchall()
    conn.close()
    
    comments = []
    for r in rows:
        comments.append({
            "id": r[0],
            "parent_id": r[1] or 0,
            "user_id": r[2],
            "username": r[3],
            "comment": r[4],
            "likes": r[5],
            "liked_by": r[6],
            "created_at": r[7],
            "updated_at": r[8]
        })
    return jsonify({"comments": comments})

@app.route('/api/comment', methods=['POST'])
def add_comment():
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO comments (post_id, parent_id, user_id, username, comment, created_at, liked_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data["post_id"],
        data.get("parent_id", 0),
        data["user_id"],
        data["username"],
        data["comment"],
        datetime.now().isoformat(),
        "[]"
    ))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route('/api/comment/<int:id>/like', methods=['POST'])
def like_comment(id):
    data = request.get_json()
    user_id = data.get("user_id")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT liked_by FROM comments WHERE id = ?", (id,))
    row = c.fetchone()
    
    if row:
        liked_by = eval(row[0]) if row[0] else []
        if user_id in liked_by:
            liked_by.remove(user_id)
        else:
            liked_by.append(user_id)
        
        c.execute("UPDATE comments SET likes = ?, liked_by = ? WHERE id = ?", 
                  (len(liked_by), str(liked_by), id))
        conn.commit()
    
    conn.close()
    return jsonify({"ok": True})

@app.route('/api/comment/<int:id>', methods=['PUT'])
def edit_comment(id):
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE comments SET comment = ?, updated_at = ? WHERE id = ? AND user_id = ?",
              (data["comment"], datetime.now().isoformat(), id, data["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route('/api/comment/<int:id>', methods=['DELETE'])
def delete_comment(id):
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM comments WHERE id = ? AND user_id = ?", (id, data["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
