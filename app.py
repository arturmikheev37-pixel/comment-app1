from flask import Flask, jsonify, render_template_string
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

# Простой HTML для теста
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Комментарии</title>
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
        .comment-form { background: #f5f5f5; padding: 20px; border-radius: 12px; margin-bottom: 20px; }
        input, textarea { width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 8px; }
        button { background: #667eea; color: white; padding: 12px; border: none; border-radius: 8px; cursor: pointer; width: 100%; }
        .comment-card { background: white; padding: 15px; border-radius: 12px; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .comment-author { font-weight: bold; }
        .comment-time { font-size: 12px; color: #888; }
    </style>
</head>
<body>
    <h1>💬 Комментарии</h1>
    <div class="comment-form">
        <input type="text" id="username" placeholder="Ваше имя">
        <textarea id="comment" placeholder="Ваш комментарий" rows="3"></textarea>
        <button onclick="sendComment()">Отправить</button>
    </div>
    <div id="comments"></div>
    
    <script>
        const postId = new URLSearchParams(window.location.search).get('startapp') || 'test';
        
        async function loadComments() {
            const res = await fetch('/api/comments/' + encodeURIComponent(postId));
            const data = await res.json();
            const container = document.getElementById('comments');
            if (data.comments && data.comments.length > 0) {
                container.innerHTML = data.comments.map(c => `
                    <div class="comment-card">
                        <div class="comment-author">${escapeHtml(c.username)}</div>
                        <div class="comment-time">${new Date(c.created_at).toLocaleString()}</div>
                        <div>${escapeHtml(c.comment)}</div>
                    </div>
                `).join('');
            } else {
                container.innerHTML = '<p>Пока нет комментариев</p>';
            }
        }
        
        async function sendComment() {
            const username = document.getElementById('username').value.trim();
            const comment = document.getElementById('comment').value.trim();
            if (!username || !comment) return alert('Заполните поля');
            
            await fetch('/api/comment', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    post_id: postId,
                    user_id: 'user_' + Date.now(),
                    username: username,
                    comment: comment
                })
            });
            document.getElementById('comment').value = '';
            loadComments();
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        loadComments();
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
    cursor.execute('SELECT username, comment, created_at FROM comments WHERE post_id = ? ORDER BY created_at DESC', (post_id,))
    rows = cursor.fetchall()
    conn.close()
    comments = [{'username': r[0], 'comment': r[1], 'created_at': r[2]} for r in rows]
    return jsonify({'comments': comments})

@app.route('/api/comment', methods=['POST'])
def add_comment():
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO comments (post_id, user_id, username, comment, created_at) VALUES (?, ?, ?, ?, ?)',
                   (data['post_id'], data['user_id'], data['username'], data['comment'], datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
