from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime
import json

app = Flask(__name__)
DB_PATH = "comments.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        comment TEXT NOT NULL,
        created_at TEXT NOT NULL
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Комментарии</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0e0e10;
            color: #e4e6eb;
            padding: 20px;
            padding-bottom: 100px;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
        }
        .post-info {
            background: #1e1e22;
            padding: 12px;
            border-radius: 12px;
            margin-bottom: 20px;
            font-size: 12px;
            color: #8e8e93;
            word-break: break-all;
            text-align: center;
        }
        .comment-form {
            background: #1e1e22;
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 20px;
        }
        .form-group {
            margin-bottom: 12px;
        }
        .form-group input, .form-group textarea {
            width: 100%;
            padding: 12px;
            background: #2c2c30;
            border: 1px solid #3a3a3e;
            border-radius: 12px;
            color: #e4e6eb;
            font-size: 15px;
            font-family: inherit;
        }
        .form-group input:focus, .form-group textarea:focus {
            outline: none;
            border-color: #0a84ff;
        }
        .form-group textarea {
            resize: vertical;
            min-height: 80px;
        }
        button {
            width: 100%;
            padding: 12px;
            background: #0a84ff;
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
        }
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .comments-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 16px;
            padding: 0 4px;
        }
        .comments-count {
            font-size: 14px;
            color: #8e8e93;
        }
        .refresh-btn {
            background: none;
            border: none;
            color: #0a84ff;
            font-size: 13px;
            cursor: pointer;
        }
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
        }
        .comment-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .comment-name {
            font-weight: 600;
            font-size: 14px;
            color: #0a84ff;
        }
        .comment-time {
            font-size: 11px;
            color: #8e8e93;
        }
        .comment-text {
            font-size: 14px;
            line-height: 1.4;
            word-break: break-word;
        }
        .empty-state {
            text-align: center;
            padding: 40px;
            color: #8e8e93;
        }
        .status {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #2c2c30;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 13px;
            opacity: 0;
            transition: opacity 0.2s;
            pointer-events: none;
        }
        .status.show {
            opacity: 1;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="post-info" id="postInfo">Загрузка...</div>
        
        <div class="comment-form">
            <div class="form-group">
                <input type="text" id="username" placeholder="Ваше имя" maxlength="50">
            </div>
            <div class="form-group">
                <textarea id="comment" placeholder="Написать комментарий..." rows="3" maxlength="500"></textarea>
            </div>
            <button id="submitBtn" onclick="sendComment()">📤 Отправить</button>
        </div>
        
        <div class="comments-header">
            <span class="comments-count" id="commentsCount">Комментарии (0)</span>
            <button class="refresh-btn" onclick="loadComments()">🔄 Обновить</button>
        </div>
        
        <div id="commentsList" class="comments-list">
            <div class="empty-state">Загрузка...</div>
        </div>
    </div>
    
    <div id="status" class="status"></div>

    <script>
        // Получаем данные из URL
        const urlParams = new URLSearchParams(window.location.search);
        const postId = urlParams.get('startapp') || urlParams.get('post_id') || 'general';
        
        // Отображаем ID поста
        document.getElementById('postInfo').innerHTML = `📌 Пост: ${postId.length > 40 ? postId.substring(0, 40) + '...' : postId}`;
        
        // Данные пользователя
        let userId = localStorage.getItem('comment_user_id');
        if (!userId) {
            userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
            localStorage.setItem('comment_user_id', userId);
        }
        
        let userName = localStorage.getItem('comment_username');
        if (!userName) {
            userName = urlParams.get('username') || 'Гость';
            localStorage.setItem('comment_username', userName);
        }
        
        document.getElementById('username').value = userName;
        document.getElementById('username').addEventListener('input', function() {
            userName = this.value.trim();
            if (userName) localStorage.setItem('comment_username', userName);
        });
        
        // Загрузка комментариев
        async function loadComments() {
            try {
                const response = await fetch(`/api/comments/${encodeURIComponent(postId)}`);
                const data = await response.json();
                const container = document.getElementById('commentsList');
                
                if (data.comments && data.comments.length > 0) {
                    container.innerHTML = '';
                    data.comments.forEach(comment => {
                        const time = new Date(comment.created_at).toLocaleString();
                        const div = document.createElement('div');
                        div.className = 'comment-card';
                        div.innerHTML = `
                            <div class="comment-header">
                                <span class="comment-name">${escapeHtml(comment.username)}</span>
                                <span class="comment-time">${time}</span>
                            </div>
                            <div class="comment-text">${escapeHtml(comment.comment)}</div>
                        `;
                        container.appendChild(div);
                    });
                } else {
                    container.innerHTML = '<div class="empty-state">💬 Нет комментариев. Будьте первым!</div>';
                }
                document.getElementById('commentsCount').textContent = `Комментарии (${data.comments?.length || 0})`;
            } catch (error) {
                console.error(error);
            }
        }
        
        // Отправка комментария
        async function sendComment() {
            const username = userName.trim();
            const commentText = document.getElementById('comment').value.trim();
            
            if (!username) {
                showStatus('Введите ваше имя', 'error');
                return;
            }
            if (!commentText) {
                showStatus('Напишите комментарий', 'error');
                return;
            }
            
            const btn = document.getElementById('submitBtn');
            btn.disabled = true;
            btn.textContent = '⏳ Отправка...';
            
            try {
                const response = await fetch('/api/comment', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        post_id: postId,
                        user_id: userId,
                        username: username,
                        comment: commentText
                    })
                });
                
                if (response.ok) {
                    document.getElementById('comment').value = '';
                    showStatus('✅ Комментарий отправлен!', 'success');
                    loadComments();
                    setTimeout(() => {
                        if (window.Maxi && window.Maxi.close) window.Maxi.close();
                    }, 1500);
                } else {
                    showStatus('❌ Ошибка отправки', 'error');
                }
            } catch (error) {
                showStatus('❌ Ошибка соединения', 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = '📤 Отправить';
            }
        }
        
        function showStatus(message, type) {
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.classList.add('show');
            setTimeout(() => statusDiv.classList.remove('show'), 2000);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        loadComments();
        setInterval(loadComments, 10000);
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
    c.execute("SELECT id, user_id, username, comment, created_at FROM comments WHERE post_id = ? ORDER BY created_at DESC", (post_id,))
    rows = c.fetchall()
    conn.close()
    comments = [{"id": r[0], "user_id": r[1], "username": r[2], "comment": r[3], "created_at": r[4]} for r in rows]
    return jsonify({"comments": comments})

@app.route('/api/comment', methods=['POST'])
def add_comment():
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO comments (post_id, user_id, username, comment, created_at) VALUES (?, ?, ?, ?, ?)",
              (data["post_id"], data["user_id"], data["username"], data["comment"], datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
