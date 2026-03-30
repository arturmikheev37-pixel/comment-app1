from datetime import datetime, timezone
import os
import sqlite3
from urllib.parse import quote_plus

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "comments.db")
DEFAULT_POST_ID = "global"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT NOT NULL DEFAULT 'global',
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    columns = {row["name"] for row in cursor.execute("PRAGMA table_info(comments)").fetchall()}
    if "post_id" not in columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN post_id TEXT NOT NULL DEFAULT 'global'")

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_comments_post_created
        ON comments (post_id, created_at DESC)
        """
    )
    conn.commit()
    conn.close()


def normalize_post_id(raw_post_id: str | None) -> str:
    value = (raw_post_id or "").strip()
    return value[:128] if value else DEFAULT_POST_ID


def normalize_username(raw_username: str | None) -> str:
    value = (raw_username or "").strip()
    return value[:50] if value else "Гость"


def normalize_comment(raw_comment: str | None) -> str:
    return (raw_comment or "").strip()[:1000]


def serialize_comment(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "post_id": row["post_id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "comment": row["comment"],
        "created_at": row["created_at"],
    }


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Комментарии</title>
    <style>
        :root {
            --bg: #eef3ea;
            --card: rgba(255, 255, 255, 0.9);
            --accent: #2f6f52;
            --accent-dark: #1f4d38;
            --text: #193126;
            --muted: #668173;
            --border: rgba(47, 111, 82, 0.14);
            --shadow: 0 18px 50px rgba(31, 77, 56, 0.12);
        }

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: "Segoe UI", "Trebuchet MS", sans-serif;
            color: var(--text);
            background:
                radial-gradient(circle at top left, rgba(96, 155, 122, 0.28), transparent 34%),
                radial-gradient(circle at bottom right, rgba(210, 181, 111, 0.24), transparent 26%),
                linear-gradient(160deg, #edf4ed 0%, #f8f4ea 100%);
            padding: 24px 14px 40px;
        }

        .shell {
            width: min(760px, 100%);
            margin: 0 auto;
        }

        .hero,
        .composer,
        .comments {
            background: var(--card);
            backdrop-filter: blur(8px);
            border: 1px solid var(--border);
            border-radius: 24px;
            box-shadow: var(--shadow);
        }

        .hero {
            padding: 24px;
            margin-bottom: 18px;
        }

        .eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 7px 12px;
            border-radius: 999px;
            background: rgba(47, 111, 82, 0.08);
            color: var(--accent-dark);
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        h1 {
            margin: 16px 0 8px;
            font-size: clamp(28px, 6vw, 42px);
            line-height: 1.05;
        }

        .hero p {
            margin: 0;
            color: var(--muted);
            font-size: 15px;
            line-height: 1.55;
        }

        .post-chip {
            margin-top: 14px;
            padding: 10px 14px;
            border-radius: 16px;
            background: rgba(25, 49, 38, 0.05);
            color: var(--muted);
            font-size: 13px;
            word-break: break-all;
        }

        .composer {
            padding: 18px;
            margin-bottom: 18px;
        }

        .field {
            margin-bottom: 12px;
        }

        .field label {
            display: block;
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 8px;
        }

        .field input,
        .field textarea {
            width: 100%;
            border: 1px solid rgba(25, 49, 38, 0.12);
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.86);
            padding: 14px 16px;
            font: inherit;
            color: var(--text);
            outline: none;
            transition: border-color .2s, transform .2s, box-shadow .2s;
        }

        .field input:focus,
        .field textarea:focus {
            border-color: rgba(47, 111, 82, 0.5);
            box-shadow: 0 0 0 4px rgba(47, 111, 82, 0.1);
            transform: translateY(-1px);
        }

        .field textarea {
            min-height: 120px;
            resize: vertical;
        }

        .toolbar {
            display: flex;
            gap: 12px;
            align-items: center;
            justify-content: space-between;
        }

        .counter {
            color: var(--muted);
            font-size: 12px;
        }

        button {
            border: none;
            border-radius: 16px;
            background: linear-gradient(135deg, var(--accent) 0%, #4b9270 100%);
            color: white;
            font: inherit;
            font-weight: 700;
            padding: 14px 18px;
            cursor: pointer;
            transition: transform .2s, opacity .2s, box-shadow .2s;
            box-shadow: 0 12px 28px rgba(47, 111, 82, 0.18);
        }

        button:hover {
            transform: translateY(-1px);
        }

        button:disabled {
            cursor: not-allowed;
            opacity: .7;
            transform: none;
        }

        .comments {
            padding: 18px;
        }

        .comments-header {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: center;
            margin-bottom: 16px;
        }

        .comments-header h2 {
            margin: 0;
            font-size: 18px;
        }

        .comments-header .refresh {
            width: auto;
            padding: 10px 14px;
            background: rgba(47, 111, 82, 0.08);
            color: var(--accent-dark);
            box-shadow: none;
        }

        .status {
            margin-top: 10px;
            padding: 12px 14px;
            border-radius: 14px;
            font-size: 13px;
            display: none;
        }

        .status.success {
            display: block;
            background: rgba(47, 111, 82, 0.1);
            color: var(--accent-dark);
        }

        .status.error {
            display: block;
            background: rgba(181, 64, 64, 0.12);
            color: #8e2d2d;
        }

        .comment-list {
            display: grid;
            gap: 12px;
        }

        .comment {
            border-radius: 20px;
            padding: 16px;
            background: rgba(255, 255, 255, 0.88);
            border: 1px solid rgba(25, 49, 38, 0.08);
        }

        .comment-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-bottom: 10px;
        }

        .author {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
        }

        .avatar {
            width: 42px;
            height: 42px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #d8e8d9 0%, #dcbf8b 100%);
            color: var(--accent-dark);
            font-weight: 800;
            flex-shrink: 0;
        }

        .author-meta {
            min-width: 0;
        }

        .name {
            font-weight: 700;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .time {
            color: var(--muted);
            font-size: 12px;
            margin-top: 2px;
        }

        .mine {
            color: var(--accent-dark);
            font-size: 11px;
            padding: 4px 8px;
            border-radius: 999px;
            background: rgba(47, 111, 82, 0.08);
            flex-shrink: 0;
        }

        .text {
            white-space: pre-wrap;
            line-height: 1.55;
            word-break: break-word;
        }

        .delete-btn {
            margin-top: 12px;
            width: auto;
            padding: 10px 12px;
            background: rgba(181, 64, 64, 0.1);
            color: #8e2d2d;
            box-shadow: none;
        }

        .empty {
            text-align: center;
            padding: 30px 16px;
            color: var(--muted);
            border: 1px dashed rgba(47, 111, 82, 0.22);
            border-radius: 18px;
        }

        @media (max-width: 640px) {
            body {
                padding: 12px 10px 28px;
            }

            .hero,
            .composer,
            .comments {
                border-radius: 20px;
            }

            .toolbar,
            .comments-header,
            .comment-top {
                flex-direction: column;
                align-items: stretch;
            }

            button,
            .comments-header .refresh,
            .delete-btn {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <main class="shell">
        <section class="hero">
            <div class="eyebrow">MAX Web App</div>
            <h1>Комментарии к посту</h1>
            <p>Эта страница открывается для конкретной публикации. Все сообщения ниже относятся только к одному посту.</p>
            <div class="post-chip">ID поста: <strong id="postIdText">{{ post_id }}</strong></div>
        </section>

        <section class="composer">
            <div class="field">
                <label for="username">Ваше имя</label>
                <input id="username" maxlength="50" placeholder="Например, Артём">
            </div>
            <div class="field">
                <label for="comment">Комментарий</label>
                <textarea id="comment" maxlength="1000" placeholder="Напишите отзыв, вопрос или идею"></textarea>
            </div>
            <div class="toolbar">
                <div class="counter"><span id="charCount">0</span>/1000</div>
                <button id="submitBtn" type="button">Отправить комментарий</button>
            </div>
            <div id="status" class="status"></div>
        </section>

        <section class="comments">
            <div class="comments-header">
                <h2 id="commentsTitle">Комментарии</h2>
                <button class="refresh" type="button" id="refreshBtn">Обновить</button>
            </div>
            <div id="commentsList" class="comment-list"></div>
        </section>
    </main>

    <script>
        const initialPostId = {{ post_id|tojson }};
        const params = new URLSearchParams(window.location.search);
        const postId = (params.get("post_id") || params.get("startapp") || initialPostId || "global").trim();
        const incomingUserId = (params.get("user_id") || "").trim();
        const incomingUsername = (params.get("username") || "").trim();

        let userId = incomingUserId || localStorage.getItem("max_comment_user_id");
        if (!userId) {
            userId = "user_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
            localStorage.setItem("max_comment_user_id", userId);
        }

        let username = incomingUsername || localStorage.getItem("max_comment_username") || "";
        const usernameInput = document.getElementById("username");
        const commentInput = document.getElementById("comment");
        const charCount = document.getElementById("charCount");
        const commentsList = document.getElementById("commentsList");
        const commentsTitle = document.getElementById("commentsTitle");
        const submitBtn = document.getElementById("submitBtn");
        const refreshBtn = document.getElementById("refreshBtn");

        document.getElementById("postIdText").textContent = postId;
        usernameInput.value = username;

        usernameInput.addEventListener("input", () => {
            username = usernameInput.value.trim();
            localStorage.setItem("max_comment_username", username);
        });

        commentInput.addEventListener("input", () => {
            charCount.textContent = commentInput.value.length;
        });

        commentInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                sendComment();
            }
        });

        refreshBtn.addEventListener("click", loadComments);
        submitBtn.addEventListener("click", sendComment);

        function escapeHtml(text) {
            const div = document.createElement("div");
            div.textContent = text;
            return div.innerHTML;
        }

        function showStatus(message, type) {
            const status = document.getElementById("status");
            status.textContent = message;
            status.className = "status " + type;
            setTimeout(() => {
                status.className = "status";
            }, 2500);
        }

        function formatDate(value) {
            try {
                return new Date(value).toLocaleString("ru-RU");
            } catch (error) {
                return value;
            }
        }

        function renderComments(comments) {
            commentsTitle.textContent = "Комментарии (" + comments.length + ")";

            if (!comments.length) {
                commentsList.innerHTML = '<div class="empty">Пока нет комментариев. Можно оставить первый.</div>';
                return;
            }

            commentsList.innerHTML = comments.map((comment) => {
                const mine = comment.user_id === userId;
                const initial = escapeHtml((comment.username || "?").charAt(0).toUpperCase());
                return `
                    <article class="comment">
                        <div class="comment-top">
                            <div class="author">
                                <div class="avatar">${initial}</div>
                                <div class="author-meta">
                                    <div class="name">${escapeHtml(comment.username)}</div>
                                    <div class="time">${formatDate(comment.created_at)}</div>
                                </div>
                            </div>
                            ${mine ? '<div class="mine">Ваш комментарий</div>' : ''}
                        </div>
                        <div class="text">${escapeHtml(comment.comment)}</div>
                        ${mine ? `<button class="delete-btn" type="button" onclick="deleteComment(${comment.id})">Удалить</button>` : ""}
                    </article>
                `;
            }).join("");
        }

        async function loadComments() {
            commentsList.innerHTML = '<div class="empty">Загрузка комментариев...</div>';
            try {
                const response = await fetch("/api/comments?post_id=" + encodeURIComponent(postId));
                const data = await response.json();
                renderComments(data.comments || []);
            } catch (error) {
                commentsList.innerHTML = '<div class="empty">Не удалось загрузить комментарии.</div>';
            }
        }

        async function sendComment() {
            const comment = commentInput.value.trim();
            const currentUsername = usernameInput.value.trim();

            if (!currentUsername) {
                showStatus("Введите имя", "error");
                usernameInput.focus();
                return;
            }

            if (!comment) {
                showStatus("Введите комментарий", "error");
                commentInput.focus();
                return;
            }

            submitBtn.disabled = true;
            submitBtn.textContent = "Отправляем...";

            try {
                const response = await fetch("/api/comment", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        post_id: postId,
                        user_id: userId,
                        username: currentUsername,
                        comment: comment
                    })
                });

                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || "Ошибка отправки");
                }

                localStorage.setItem("max_comment_username", currentUsername);
                commentInput.value = "";
                charCount.textContent = "0";
                showStatus("Комментарий отправлен", "success");
                await loadComments();
            } catch (error) {
                showStatus(error.message || "Не удалось отправить комментарий", "error");
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = "Отправить комментарий";
            }
        }

        async function deleteComment(commentId) {
            try {
                const response = await fetch("/api/comment/" + commentId, {
                    method: "DELETE",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: userId })
                });

                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || "Ошибка удаления");
                }

                showStatus("Комментарий удалён", "success");
                await loadComments();
            } catch (error) {
                showStatus(error.message || "Не удалось удалить комментарий", "error");
            }
        }

        window.deleteComment = deleteComment;
        loadComments();
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    post_id = normalize_post_id(request.args.get("post_id") or request.args.get("startapp"))
    return render_template_string(HTML_TEMPLATE, post_id=post_id)


@app.route("/post/<post_id>")
def post_page(post_id):
    return render_template_string(HTML_TEMPLATE, post_id=normalize_post_id(post_id))


@app.route("/api/comments")
def get_comments():
    post_id = normalize_post_id(request.args.get("post_id"))
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, post_id, user_id, username, comment, created_at
        FROM comments
        WHERE post_id = ?
        ORDER BY created_at DESC
        """,
        (post_id,),
    ).fetchall()
    conn.close()
    return jsonify({"post_id": post_id, "comments": [serialize_comment(row) for row in rows]})


@app.route("/api/post_count/<path:post_id>")
def get_post_count(post_id):
    normalized_post_id = normalize_post_id(post_id)
    conn = get_db_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM comments WHERE post_id = ?",
        (normalized_post_id,),
    ).fetchone()
    conn.close()
    return jsonify({"post_id": normalized_post_id, "count": row["count"]})


@app.route("/api/comment", methods=["POST"])
def add_comment():
    payload = request.get_json(silent=True) or {}
    post_id = normalize_post_id(payload.get("post_id"))
    user_id = (payload.get("user_id") or "").strip()[:128]
    username = normalize_username(payload.get("username"))
    comment = normalize_comment(payload.get("comment"))

    if not user_id:
        return jsonify({"error": "Не передан user_id"}), 400
    if not comment:
        return jsonify({"error": "Комментарий пустой"}), 400

    created_at = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO comments (post_id, user_id, username, comment, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (post_id, user_id, username, comment, created_at),
    )
    conn.commit()
    comment_id = cursor.lastrowid
    conn.close()

    return jsonify(
        {
            "status": "success",
            "comment": {
                "id": comment_id,
                "post_id": post_id,
                "user_id": user_id,
                "username": username,
                "comment": comment,
                "created_at": created_at,
            },
        }
    )


@app.route("/api/comment/<int:comment_id>", methods=["DELETE"])
def delete_comment(comment_id):
    payload = request.get_json(silent=True) or {}
    user_id = (payload.get("user_id") or "").strip()[:128]
    if not user_id:
        return jsonify({"error": "Не передан user_id"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM comments WHERE id = ? AND user_id = ?", (comment_id, user_id))
    conn.commit()
    deleted = cursor.rowcount
    conn.close()

    if not deleted:
        return jsonify({"error": "Комментарий не найден или нет прав"}), 404
    return jsonify({"status": "success"})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "db_exists": os.path.exists(DB_PATH)})


@app.route("/api/share_link/<path:post_id>")
def share_link(post_id):
    normalized_post_id = normalize_post_id(post_id)
    base_url = request.host_url.rstrip("/")
    return jsonify(
        {
            "post_id": normalized_post_id,
            "web_app_url": f"{base_url}/?post_id={quote_plus(normalized_post_id)}",
        }
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000, debug=True)
else:
    init_db()
