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

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Комментарии</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            padding-bottom: 20px;
        }

        /* Фиксированная форма внизу */
        .comment-form-fixed {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: white;
            border-top: 1px solid #e0e0e0;
            padding: 12px 16px;
            box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.05);
            z-index: 100;
        }

        .form-row {
            display: flex;
            gap: 10px;
            align-items: flex-end;
        }

        .input-group {
            flex: 1;
        }

        .input-group input {
            width: 100%;
            padding: 12px 14px;
            border: 1px solid #e0e0e0;
            border-radius: 24px;
            font-size: 15px;
            background: #f8f9fa;
            transition: all 0.2s;
        }

        .input-group input:focus {
            outline: none;
            border-color: #667eea;
            background: white;
        }

        .input-group textarea {
            width: 100%;
            padding: 12px 14px;
            border: 1px solid #e0e0e0;
            border-radius: 24px;
            font-size: 15px;
            font-family: inherit;
            resize: none;
            background: #f8f9fa;
            transition: all 0.2s;
            min-height: 44px;
            max-height: 100px;
        }

        .input-group textarea:focus {
            outline: none;
            border-color: #667eea;
            background: white;
        }

        .send-btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            width: 44px;
            height: 44px;
            border-radius: 44px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: transform 0.1s, opacity 0.2s;
            flex-shrink: 0;
        }

        .send-btn:active {
            transform: scale(0.95);
        }

        .send-btn.disabled {
            opacity: 0.5;
            pointer-events: none;
        }

        .send-btn svg {
            width: 22px;
            height: 22px;
            fill: white;
        }

        /* Основной контент */
        .content {
            padding: 16px 16px 100px 16px;
        }

        /* Заголовок поста */
        .post-header {
            background: white;
            border-radius: 20px;
            padding: 16px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        }

        .post-title {
            font-weight: 600;
            font-size: 16px;
            color: #333;
            margin-bottom: 8px;
        }

        .post-id {
            font-size: 11px;
            color: #999;
            word-break: break-all;
            background: #f5f5f5;
            padding: 6px 10px;
            border-radius: 12px;
            display: inline-block;
        }

        /* Счетчик комментариев */
        .comments-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
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
            transition: background 0.2s;
        }

        .refresh-btn:active {
            background: #f0f0f0;
        }

        /* Список комментариев */
        .comments-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .comment-card {
            background: white;
            border-radius: 20px;
            padding: 14px 16px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
            transition: all 0.2s;
        }

        .comment-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 8px;
        }

        .comment-avatar {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 16px;
            flex-shrink: 0;
        }

        .comment-info {
            flex: 1;
        }

        .comment-author {
            font-weight: 600;
            color: #333;
            font-size: 15px;
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
        }

        .comment-badge {
            font-size: 11px;
            background: #e8f0fe;
            color: #667eea;
            padding: 2px 8px;
            border-radius: 12px;
            font-weight: normal;
        }

        .comment-time {
            font-size: 11px;
            color: #999;
            margin-top: 2px;
        }

        .comment-text {
            color: #444;
            font-size: 14px;
            line-height: 1.45;
            margin: 8px 0 8px 52px;
            word-break: break-word;
        }

        .comment-actions {
            margin-left: 52px;
            display: flex;
            gap: 12px;
        }

        .comment-actions button {
            background: none;
            border: none;
            font-size: 12px;
            color: #999;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 16px;
            transition: all 0.2s;
        }

        .comment-actions button:active {
            background: #f0f0f0;
        }

        .comment-actions .delete-btn {
            color: #e74c3c;
        }

        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #999;
        }

        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }

        .empty-state-text {
            font-size: 14px;
        }

        .status-message {
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 8px 16px;
            border-radius: 40px;
            font-size: 13px;
            z-index: 200;
            white-space: nowrap;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.2s;
        }

        .status-message.show {
            opacity: 1;
        }

        .status-message.success {
            background: #2ecc71;
        }

        .status-message.error {
            background: #e74c3c;
        }

        .loading {
            text-align: center;
            padding: 40px;
            color: #999;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .comment-card {
            animation: fadeIn 0.2s ease;
        }

        /* Адаптация под маленькие экраны */
        @media (max-width: 480px) {
            .form-row {
                gap: 8px;
            }
            .input-group input, .input-group textarea {
                font-size: 14px;
                padding: 10px 14px;
            }
            .send-btn {
                width: 40px;
                height: 40px;
            }
            .comment-text {
                margin-left: 44px;
            }
            .comment-actions {
                margin-left: 44px;
            }
        }
    </style>
</head>
<body>
    <div class="content">
        <!-- Информация о посте -->
        <div class="post-header" id="postHeader">
            <div class="post-title">💬 Комментарии</div>
            <div class="post-id" id="postIdDisplay"></div>
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

    <!-- Фиксированная форма внизу -->
    <div class="comment-form-fixed">
        <div class="form-row">
            <div class="input-group">
                <input type="text" id="usernameInput" placeholder="Ваше имя" maxlength="50">
            </div>
            <div class="input-group">
                <textarea id="commentInput" placeholder="Написать комментарий..." rows="1" maxlength="500"></textarea>
            </div>
            <button class="send-btn" id="submitBtn" onclick="submitComment()">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                </svg>
            </button>
        </div>
    </div>

    <div id="statusMessage" class="status-message"></div>

    <script>
        // ⭐ Получаем post_id из URL
        const urlParams = new URLSearchParams(window.location.search);
        let postId = urlParams.get('startapp') || urlParams.get('post_id');
        
        // Если post_id нет — показываем ошибку
        if (!postId) {
            document.getElementById('postIdDisplay').innerHTML = '❌ Ошибка: не удалось определить пост';
            document.getElementById('commentsList').innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <div class="empty-state-text">Не удалось определить пост</div>
                    <div style="font-size: 12px; margin-top: 8px;">Перейдите по ссылке из канала MAX</div>
                </div>
            `;
            document.getElementById('submitBtn').classList.add('disabled');
            document.getElementById('usernameInput').disabled = true;
            document.getElementById('commentInput').disabled = true;
        } else {
            document.getElementById('postIdDisplay').innerHTML = `📌 ${postId.length > 40 ? postId.substring(0, 40) + '...' : postId}`;
        }
        
        // ID текущего пользователя
        let currentUserId = localStorage.getItem('comment_user_id');
        if (!currentUserId) {
            currentUserId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 8);
            localStorage.setItem('comment_user_id', currentUserId);
        }
        
        // Имя пользователя
        let currentUsername = localStorage.getItem('comment_username') || '';
        
        if (currentUsername) {
            document.getElementById('usernameInput').value = currentUsername;
        }
        
        // Сохраняем имя при вводе
        document.getElementById('usernameInput').addEventListener('input', function() {
            currentUsername = this.value.trim();
            localStorage.setItem('comment_username', currentUsername);
        });
        
        // Автоматическое расширение textarea
        const commentInput = document.getElementById('commentInput');
        commentInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 100) + 'px';
        });
        
        // Отправка по Enter (Ctrl+Enter или просто Enter)
        commentInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitComment();
            }
        });
        
        // Загрузка комментариев
        async function loadComments() {
            if (!postId) return;
            
            try {
                const response = await fetch(`/api/comments/${encodeURIComponent(postId)}`);
                const data = await response.json();
                const commentsList = document.getElementById('commentsList');
                
                if (data.comments && data.comments.length > 0) {
                    commentsList.innerHTML = '';
                    data.comments.forEach(comment => addCommentToDOM(comment));
                } else {
                    commentsList.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">💬</div>
                            <div class="empty-state-text">Пока нет комментариев</div>
                            <div style="font-size: 12px; margin-top: 8px;">Будьте первым!</div>
                        </div>
                    `;
                }
                document.getElementById('commentsCount').textContent = `Комментарии (${data.comments?.length || 0})`;
            } catch (error) {
                console.error('Ошибка загрузки:', error);
                document.getElementById('commentsList').innerHTML = '<div class="empty-state">⚠️ Ошибка загрузки</div>';
            }
        }
        
        function addCommentToDOM(comment) {
            const commentsList = document.getElementById('commentsList');
            const time = new Date(comment.created_at).toLocaleString('ru-RU');
            const avatarLetter = (comment.username.charAt(0) || '?').toUpperCase();
            const isCurrentUser = comment.user_id === currentUserId;
            
            const commentDiv = document.createElement('div');
            commentDiv.className = 'comment-card';
            commentDiv.id = `comment-${comment.id}`;
            commentDiv.innerHTML = `
                <div class="comment-header">
                    <div class="comment-avatar">${escapeHtml(avatarLetter)}</div>
                    <div class="comment-info">
                        <div class="comment-author">
                            ${escapeHtml(comment.username)}
                            ${isCurrentUser ? '<span class="comment-badge">Вы</span>' : ''}
                        </div>
                        <div class="comment-time">${time}</div>
                    </div>
                </div>
                <div class="comment-text">${escapeHtml(comment.comment)}</div>
                ${isCurrentUser ? `
                    <div class="comment-actions">
                        <button class="delete-btn" onclick="deleteComment(${comment.id})">🗑 Удалить</button>
                    </div>
                ` : ''}
            `;
            commentsList.insertBefore(commentDiv, commentsList.firstChild);
        }
        
        async function submitComment() {
            if (!postId) {
                showStatus('❌ Ошибка: пост не найден', 'error');
                return;
            }
            
            const username = currentUsername.trim();
            const comment = commentInput.value.trim();
            
            if (!username) {
                showStatus('❌ Введите ваше имя', 'error');
                document.getElementById('usernameInput').focus();
                return;
            }
            if (!comment) {
                showStatus('❌ Введите комментарий', 'error');
                commentInput.focus();
                return;
            }
            
            const button = document.getElementById('submitBtn');
            button.classList.add('disabled');
            
            try {
                const response = await fetch('/api/comment', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        post_id: postId,
                        user_id: currentUserId,
                        username: username,
                        comment: comment
                    })
                });
                
                if (response.ok) {
                    showStatus('✅ Комментарий отправлен!', 'success');
                    commentInput.value = '';
                    commentInput.style.height = 'auto';
                    await loadComments();
                    setTimeout(() => {
                        if (window.Maxi && window.Maxi.close) {
                            window.Maxi.close();
                        }
                    }, 1000);
                } else {
                    const data = await response.json();
                    showStatus(data.error || '❌ Ошибка отправки', 'error');
                }
            } catch (error) {
                console.error('Ошибка:', error);
                showStatus('❌ Ошибка соединения', 'error');
            } finally {
                button.classList.remove('disabled');
            }
        }
        
        async function deleteComment(commentId) {
            if (!confirm('Удалить комментарий?')) return;
            
            try {
                const response = await fetch(`/api/comment/${commentId}`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: currentUserId })
                });
                if (response.ok) {
                    loadComments();
                    showStatus('🗑 Комментарий удален', 'success');
                }
            } catch (error) {
                console.error('Ошибка удаления:', error);
                showStatus('❌ Ошибка удаления', 'error');
            }
        }
        
        function showStatus(message, type) {
            const statusDiv = document.getElementById('statusMessage');
            statusDiv.textContent = message;
            statusDiv.className = `status-message ${type} show`;
            setTimeout(() => {
                statusDiv.classList.remove('show');
            }, 2000);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Загружаем комментарии при старте
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
    """Получить комментарии для конкретного поста"""
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
    """Добавить новый комментарий"""
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
    """Удалить комментарий (только свои)"""
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
    """Проверка работоспособности"""
    return jsonify({'status': 'ok', 'db_exists': os.path.exists(DB_PATH)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
