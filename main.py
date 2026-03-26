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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Комментарии</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 16px;
            min-height: 100vh;
        }
        .container { max-width: 600px; margin: 0 auto; }
        .comment-form {
            background: white;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }
        .form-group { margin-bottom: 16px; }
        .form-group label {
            display: block;
            font-size: 14px;
            font-weight: 500;
            color: #666;
            margin-bottom: 8px;
        }
        .form-group input, .form-group textarea {
            width: 100%;
            padding: 12px;
            border: 1px solid #e0e0e0;
            border-radius: 12px;
            font-size: 15px;
            font-family: inherit;
        }
        .form-group input:focus, .form-group textarea:focus {
            outline: none;
            border-color: #667eea;
        }
        .form-group textarea { resize: vertical; min-height: 80px; }
        .char-count { text-align: right; font-size: 12px; color: #999; margin-top: 4px; }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        button:hover { opacity: 0.9; }
        button:disabled { opacity: 0.6; cursor: not-allowed; }
        .comments-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .comments-count { font-size: 14px; color: #666; font-weight: 500; }
        .comments-list { display: flex; flex-direction: column; gap: 12px; }
        .comment-card {
            background: white;
            border-radius: 16px;
            padding: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .comment-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 10px;
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
        .comment-info { flex: 1; }
        .comment-author { font-weight: 600; color: #333; font-size: 15px; }
        .comment-time { font-size: 11px; color: #999; margin-top: 2px; }
        .comment-text {
            color: #555;
            font-size: 14px;
            line-height: 1.5;
            margin-bottom: 10px;
            word-break: break-word;
            padding-left: 52px;
        }
        .comment-actions { padding-left: 52px; }
        .comment-actions span {
            font-size: 12px;
            color: #888;
            cursor: pointer;
            transition: color 0.2s;
        }
        .comment-actions span:hover { color: #667eea; }
        .empty-state { text-align: center; padding: 48px 20px; color: #999; }
        .empty-state-icon { font-size: 48px; margin-bottom: 12px; }
        .status {
            margin-top: 16px;
            padding: 12px;
            border-radius: 12px;
            text-align: center;
            font-size: 13px;
            display: none;
        }
        .status.success { background: #d4edda; color: #155724; display: block; }
        .status.error { background: #f8d7da; color: #721c24; display: block; }
        .loading { text-align: center; padding: 40px; color: #999; }
        .info-bar {
            font-size: 12px;
            color: #888;
            text-align: center;
            margin-top: 16px;
            padding: 8px;
            background: #e8f0fe;
            border-radius: 8px;
            word-break: break-all;
        }
        .refresh-btn {
            background: none;
            color: #667eea;
            font-size: 12px;
            padding: 4px 12px;
            width: auto;
            cursor: pointer;
            border: 1px solid #e0e0e0;
            border-radius: 20px;
        }
        .refresh-btn:hover { background: #f0f0f0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="comment-form">
            <div class="form-group">
                <label>👤 Ваше имя</label>
                <input type="text" id="usernameInput" placeholder="Как вас называть?" maxlength="50">
            </div>
            <div class="form-group">
                <label>💬 Комментарий</label>
                <textarea id="commentInput" placeholder="Напишите ваш комментарий..." maxlength="500"></textarea>
                <div class="char-count"><span id="charCount">0</span>/500</div>
            </div>
            <button id="submitBtn" onclick="submitComment()">📤 Отправить комментарий</button>
            <div id="status" class="status"></div>
        </div>

        <div class="comments-header">
            <span class="comments-count" id="commentsCount">Комментарии (0)</span>
            <button class="refresh-btn" onclick="loadComments()">🔄 Обновить</button>
        </div>
        <div id="commentsList" class="comments-list">
            <div class="loading">Загрузка комментариев...</div>
        </div>
        <div class="info-bar" id="postIdInfo"></div>
    </div>

    <script>
        // ⭐ КЛЮЧЕВОЙ МОМЕНТ: получаем post_id из URL
        const urlParams = new URLSearchParams(window.location.search);
        let postId = urlParams.get('startapp') || urlParams.get('post_id');
        
        // Если post_id нет — показываем ошибку
        if (!postId) {
            document.getElementById('commentsList').innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <div>Ошибка: не удалось определить пост</div>
                    <div style="font-size: 13px; margin-top: 8px;">Перейдите по ссылке из канала MAX</div>
                </div>
            `;
            document.getElementById('submitBtn').disabled = true;
        }
        
        // ID текущего пользователя
        let currentUserId = localStorage.getItem('comment_user_id');
        if (!currentUserId) {
            currentUserId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 8);
            localStorage.setItem('comment_user_id', currentUserId);
        }
        
        // Имя пользователя
        let currentUsername = localStorage.getItem('comment_username') || '';
        
        // Отображаем ID поста
        if (postId) {
            document.getElementById('postIdInfo').innerHTML = `📌 Пост: ${postId.substring(0, 40)}${postId.length > 40 ? '...' : ''}`;
        }
        
        // Заполняем имя, если сохранено
        if (currentUsername) {
            document.getElementById('usernameInput').value = currentUsername;
        }
        
        // Сохраняем имя при вводе
        document.getElementById('usernameInput').addEventListener('input', function() {
            currentUsername = this.value;
            localStorage.setItem('comment_username', currentUsername);
        });
        
        // Счетчик символов
        const commentInput = document.getElementById('commentInput');
        const charCountSpan = document.getElementById('charCount');
        commentInput.addEventListener('input', function() {
            charCountSpan.textContent = this.value.length;
        });
        
        // Загрузка комментариев для КОНКРЕТНОГО поста
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
                            <div>Пока нет комментариев</div>
                            <div style="font-size: 13px; margin-top: 8px;">Будьте первым!</div>
                        </div>
                    `;
                }
                document.getElementById('commentsCount').textContent = `Комментарии (${data.comments?.length || 0})`;
            } catch (error) {
                console.error('Ошибка загрузки:', error);
                document.getElementById('commentsList').innerHTML = '<div class="empty-state">⚠️ Ошибка загрузки</div>';
            }
        }
        
        // Добавление комментария в DOM
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
                        <div class="comment-author">${escapeHtml(comment.username)} ${isCurrentUser ? '(Вы)' : ''}</div>
                        <div class="comment-time">${time}</div>
                    </div>
                </div>
                <div class="comment-text">${escapeHtml(comment.comment)}</div>
                ${isCurrentUser ? `<div class="comment-actions"><span onclick="deleteComment(${comment.id})">🗑 Удалить</span></div>` : ''}
            `;
            commentsList.insertBefore(commentDiv, commentsList.firstChild);
        }
        
        // Отправка комментария
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
            button.disabled = true;
            button.textContent = '⏳ Отправка...';
            
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
                    charCountSpan.textContent = '0';
                    // Обновляем список комментариев
                    await loadComments();
                    // Закрываем мини-приложение через 2 секунды
                    setTimeout(() => {
                        if (window.Maxi && window.Maxi.close) {
                            window.Maxi.close();
                        }
                    }, 1500);
                } else {
                    const data = await response.json();
                    showStatus(data.error || '❌ Ошибка отправки', 'error');
                }
            } catch (error) {
                console.error('Ошибка:', error);
                showStatus('❌ Ошибка соединения', 'error');
            } finally {
                button.disabled = false;
                button.textContent = '📤 Отправить комментарий';
            }
        }
        
        // Удаление комментария
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
                }
            } catch (error) {
                console.error('Ошибка удаления:', error);
            }
        }
        
        function showStatus(message, type) {
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.className = `status ${type}`;
            setTimeout(() => {
                statusDiv.className = 'status';
            }, 3000);
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
