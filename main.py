from flask import Flask, request, jsonify, render_template_string
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'comments.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

init_db()

# Простой и красивый HTML без сложной анимации
HTML_TEMPLATE = '''
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
            background: #ffffff;
            padding: 16px;
            padding-bottom: 100px;
        }
        
        .container {
            max-width: 600px;
            margin: 0 auto;
        }
        
        /* Информация о посте */
        .post-info {
            background: #f8f9fa;
            padding: 12px 16px;
            border-radius: 12px;
            margin-bottom: 20px;
            font-size: 12px;
            color: #666;
            word-break: break-all;
            border: 1px solid #e9ecef;
        }
        
        /* Форма добавления комментария */
        .comment-form {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        
        .form-group {
            margin-bottom: 12px;
        }
        
        .form-group input {
            width: 100%;
            padding: 12px 14px;
            border: 1px solid #dee2e6;
            border-radius: 12px;
            font-size: 15px;
            background: white;
        }
        
        .form-group input:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .form-group textarea {
            width: 100%;
            padding: 12px 14px;
            border: 1px solid #dee2e6;
            border-radius: 12px;
            font-size: 15px;
            font-family: inherit;
            resize: vertical;
            min-height: 80px;
        }
        
        .form-group textarea:focus {
            outline: none;
            border-color: #667eea;
        }
        
        button {
            width: 100%;
            padding: 12px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        
        button:active {
            opacity: 0.8;
        }
        
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        /* Заголовок списка комментариев */
        .comments-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding: 0 4px;
        }
        
        .comments-count {
            font-size: 15px;
            font-weight: 600;
            color: #333;
        }
        
        .refresh-btn {
            background: none;
            border: none;
            color: #667eea;
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
            background: #f8f9fa;
            border-radius: 16px;
            padding: 14px;
            border: 1px solid #e9ecef;
        }
        
        .comment-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }
        
        .comment-avatar {
            width: 36px;
            height: 36px;
            background: #667eea;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 14px;
            flex-shrink: 0;
        }
        
        .comment-info {
            flex: 1;
        }
        
        .comment-name {
            font-weight: 600;
            color: #333;
            font-size: 14px;
        }
        
        .comment-badge {
            font-size: 10px;
            background: #e8f0fe;
            color: #667eea;
            padding: 2px 8px;
            border-radius: 12px;
            margin-left: 6px;
            font-weight: normal;
        }
        
        .comment-time {
            font-size: 10px;
            color: #999;
            margin-top: 2px;
        }
        
        .comment-text {
            color: #444;
            font-size: 14px;
            line-height: 1.4;
            margin-top: 6px;
            margin-left: 46px;
            word-break: break-word;
        }
        
        .delete-btn {
            background: none;
            border: none;
            font-size: 11px;
            color: #e74c3c;
            cursor: pointer;
            margin-left: 46px;
            margin-top: 6px;
            padding: 4px 8px;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: #999;
            background: #f8f9fa;
            border-radius: 16px;
        }
        
        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 12px;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #999;
        }
        
        .status {
            margin-top: 12px;
            padding: 10px;
            border-radius: 12px;
            text-align: center;
            font-size: 13px;
            display: none;
        }
        
        .status.success {
            background: #d4edda;
            color: #155724;
            display: block;
        }
        
        .status.error {
            background: #f8d7da;
            color: #721c24;
            display: block;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Информация о посте -->
        <div class="post-info" id="postInfo">
            Загрузка информации о посте...
        </div>
        
        <!-- Форма добавления комментария -->
        <div class="comment-form">
            <div class="form-group">
                <input type="text" id="username" placeholder="Ваше имя" maxlength="50">
            </div>
            <div class="form-group">
                <textarea id="comment" placeholder="Написать комментарий..." rows="3" maxlength="500"></textarea>
            </div>
            <button id="submitBtn" onclick="sendComment()">📤 Отправить</button>
            <div id="status" class="status"></div>
        </div>
        
        <!-- Заголовок списка -->
        <div class="comments-header">
            <span class="comments-count" id="commentsCount">Комментарии (0)</span>
            <button class="refresh-btn" onclick="loadComments()">🔄 Обновить</button>
        </div>
        
        <!-- Список комментариев -->
        <div id="commentsList" class="comments-list">
            <div class="loading">Загрузка комментариев...</div>
        </div>
    </div>

    <script>
        // Получаем post_id из URL
        const urlParams = new URLSearchParams(window.location.search);
        let postId = urlParams.get('startapp') || urlParams.get('post_id');
        
        // Показываем информацию о посте
        if (postId) {
            document.getElementById('postInfo').innerHTML = `📌 Пост: ${postId.length > 50 ? postId.substring(0, 50) + '...' : postId}`;
        } else {
            document.getElementById('postInfo').innerHTML = `⚠️ Ошибка: не удалось определить пост. Перейдите по ссылке из канала MAX.`;
            document.getElementById('submitBtn').disabled = true;
            document.getElementById('username').disabled = true;
            document.getElementById('comment').disabled = true;
        }
        
        // ID пользователя
        let userId = localStorage.getItem('comment_user_id');
        if (!userId) {
            userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
            localStorage.setItem('comment_user_id', userId);
        }
        
        // Имя пользователя
        let userName = localStorage.getItem('comment_username') || '';
        if (userName) {
            document.getElementById('username').value = userName;
        }
        
        // Сохраняем имя
        document.getElementById('username').addEventListener('input', function() {
            userName = this.value.trim();
            localStorage.setItem('comment_username', userName);
        });
        
        // Загрузка комментариев
        async function loadComments() {
            if (!postId) return;
            
            try {
                const response = await fetch(`/api/comments/${encodeURIComponent(postId)}`);
                const data = await response.json();
                const container = document.getElementById('commentsList');
                
                if (data.comments && data.comments.length > 0) {
                    container.innerHTML = '';
                    data.comments.forEach(comment => addComment(comment));
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
        
        function addComment(comment) {
            const container = document.getElementById('commentsList');
            const time = new Date(comment.created_at).toLocaleString('ru-RU');
            const letter = (comment.username.charAt(0) || '?').toUpperCase();
            const isMine = comment.user_id === userId;
            
            const div = document.createElement('div');
            div.className = 'comment-card';
            div.innerHTML = `
                <div class="comment-header">
                    <div class="comment-avatar">${escapeHtml(letter)}</div>
                    <div class="comment-info">
                        <div>
                            <span class="comment-name">${escapeHtml(comment.username)}</span>
                            ${isMine ? '<span class="comment-badge">Вы</span>' : ''}
                        </div>
                        <div class="comment-time">${time}</div>
                    </div>
                </div>
                <div class="comment-text">${escapeHtml(comment.comment)}</div>
                ${isMine ? `<button class="delete-btn" onclick="deleteComment(${comment.id})">🗑 Удалить</button>` : ''}
            `;
            container.insertBefore(div, container.firstChild);
        }
        
        async function sendComment() {
            const username = userName.trim();
            const commentText = document.getElementById('comment').value.trim();
            
            if (!username) {
                showStatus('Введите ваше имя', 'error');
                document.getElementById('username').focus();
                return;
            }
            if (!commentText) {
                showStatus('Введите комментарий', 'error');
                document.getElementById('comment').focus();
                return;
            }
            if (!postId) {
                showStatus('Ошибка: пост не найден', 'error');
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
                    showStatus('✅ Комментарий отправлен!', 'success');
                    document.getElementById('comment').value = '';
                    await loadComments();
                    setTimeout(() => {
                        if (window.Maxi && window.Maxi.close) window.Maxi.close();
                    }, 1500);
                } else {
                    const data = await response.json();
                    showStatus(data.error || 'Ошибка отправки', 'error');
                }
            } catch (error) {
                showStatus('Ошибка соединения', 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = '📤 Отправить';
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
                    showStatus('Комментарий удален', 'success');
                }
            } catch (error) {
                showStatus('Ошибка удаления', 'error');
            }
        }
        
        function showStatus(message, type) {
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.className = `status ${type}`;
            setTimeout(() => {
                statusDiv.className = 'status';
            }, 2000);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Запуск
        if (postId) {
            loadComments();
        }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/comments/<post_id>')
def get_comments(post_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_id, username, comment, created_at 
        FROM comments 
        WHERE post_id = ? 
        ORDER BY created_at DESC
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
    try:
        data = request.get_json()
        post_id = data.get('post_id')
        user_id = data.get('user_id')
        username = data.get('username')
        comment = data.get('comment')
        
        if not all([post_id, user_id, username, comment]):
            return jsonify({'error': 'Missing fields'}), 400
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO comments (post_id, user_id, username, comment, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (post_id, user_id, username, comment, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/comment/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM comments WHERE id = ? AND user_id = ?', (comment_id, user_id))
        conn.commit()
        conn.close()
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'db_exists': os.path.exists(DB_PATH)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
