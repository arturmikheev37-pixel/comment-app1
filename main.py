from datetime import datetime, timezone
import os
import sqlite3
from urllib.parse import quote

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "comments.db")


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
            post_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    columns = {row["name"] for row in cursor.execute("PRAGMA table_info(comments)").fetchall()}
    if "post_id" not in columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN post_id TEXT")
        cursor.execute("UPDATE comments SET post_id = id WHERE post_id IS NULL OR TRIM(post_id) = ''")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comments_post_created ON comments (post_id, created_at DESC)")
    else:
        cursor.execute(
            """
            UPDATE comments
            SET post_id = id
            WHERE post_id IS NULL OR TRIM(post_id) = '' OR post_id = 'global'
            """
        )
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
    return value[:128]


def require_post_id(raw_post_id: str | None) -> str:
    post_id = normalize_post_id(raw_post_id)
    if not post_id:
        raise ValueError("Не передан post_id")
    return post_id


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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Комментарии</title>
    <style>
        :root {
            --tg-bg: #0e1621;
            --tg-panel: #17212b;
            --tg-panel-border: #23303d;
            --tg-outgoing: #2b5278;
            --tg-incoming: #182533;
            --tg-accent: #2ea6ff;
            --tg-text: #ffffff;
            --tg-muted: #8e9aa5;
            --tg-danger: #ff5959;
        }

        * {
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }

        html, body {
            margin: 0;
            min-height: 100%;
            background: var(--tg-bg);
            color: var(--tg-text);
            font-family: "Segoe UI", Tahoma, sans-serif;
        }

        body {
            background-image:
                radial-gradient(circle at 20% 10%, rgba(46, 166, 255, 0.08), transparent 20%),
                radial-gradient(circle at 80% 0%, rgba(43, 82, 120, 0.22), transparent 22%),
                url("https://telegram.org/img/tgme/pattern.svg");
            background-repeat: repeat;
        }

        .app {
            width: min(760px, 100%);
            margin: 0 auto;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            backdrop-filter: blur(2px);
        }

        .topbar {
            position: sticky;
            top: 0;
            z-index: 5;
            padding: 14px 16px 12px;
            background: rgba(23, 33, 43, 0.92);
            border-bottom: 1px solid var(--tg-panel-border);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18);
        }

        .title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 17px;
            font-weight: 700;
        }

        .title-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #52d273;
            box-shadow: 0 0 10px rgba(82, 210, 115, 0.6);
        }

        .subtitle {
            margin-top: 4px;
            color: var(--tg-muted);
            font-size: 12px;
            word-break: break-all;
        }

        .feed {
            flex: 1;
            padding: 16px 12px 110px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .welcome {
            align-self: center;
            background: rgba(33, 47, 60, 0.78);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 16px;
            padding: 10px 14px;
            text-align: center;
            color: var(--tg-muted);
            font-size: 13px;
            max-width: 420px;
            line-height: 1.5;
        }

        .message-row {
            display: flex;
            gap: 8px;
            align-items: flex-end;
        }

        .message-row.mine {
            justify-content: flex-end;
        }

        .avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #2ea6ff, #5c6ac4);
            color: white;
            font-weight: 700;
            flex-shrink: 0;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.24);
        }

        .bubble {
            max-width: min(85%, 560px);
            padding: 10px 12px 8px;
            border-radius: 18px 18px 18px 6px;
            background: var(--tg-incoming);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
        }

        .message-row.mine .bubble {
            background: var(--tg-outgoing);
            border-radius: 18px 18px 6px 18px;
        }

        .message-name {
            color: #6ab3ff;
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 4px;
        }

        .message-text {
            white-space: pre-wrap;
            word-break: break-word;
            font-size: 14px;
            line-height: 1.45;
            color: var(--tg-text);
        }

        .message-meta {
            margin-top: 6px;
            display: flex;
            justify-content: flex-end;
            gap: 8px;
            align-items: center;
            color: #9db2c6;
            font-size: 11px;
        }

        .message-delete {
            cursor: pointer;
            color: #ffd5d5;
        }

        .empty {
            align-self: center;
            margin-top: 28px;
            text-align: center;
            color: var(--tg-muted);
            background: rgba(23, 33, 43, 0.84);
            padding: 18px 20px;
            border-radius: 18px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }

        .composer {
            position: fixed;
            left: 50%;
            bottom: 0;
            transform: translateX(-50%);
            width: min(760px, 100%);
            padding: 10px 10px calc(10px + env(safe-area-inset-bottom));
            background: linear-gradient(to top, rgba(14, 22, 33, 0.98), rgba(14, 22, 33, 0.74));
        }

        .composer-card {
            background: rgba(23, 33, 43, 0.96);
            border: 1px solid var(--tg-panel-border);
            border-radius: 24px;
            padding: 10px;
            box-shadow: 0 12px 34px rgba(0, 0, 0, 0.28);
        }

        .identity {
            display: flex;
            gap: 8px;
            margin-bottom: 8px;
        }

        .identity input {
            width: 100%;
            background: #223140;
            border: 1px solid transparent;
            color: white;
            border-radius: 16px;
            padding: 10px 12px;
            outline: none;
            font: inherit;
        }

        .identity input:focus,
        .composer-card textarea:focus {
            border-color: rgba(46, 166, 255, 0.7);
        }

        .composer-card textarea {
            width: 100%;
            min-height: 62px;
            max-height: 180px;
            resize: vertical;
            background: #223140;
            border: 1px solid transparent;
            color: white;
            border-radius: 18px;
            padding: 12px 14px;
            outline: none;
            font: inherit;
            line-height: 1.4;
        }

        .composer-actions {
            margin-top: 8px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }

        .hint,
        .status {
            font-size: 12px;
            color: var(--tg-muted);
        }

        .status.error {
            color: #ff9c9c;
        }

        .status.success {
            color: #8de5aa;
        }

        .send-btn {
            border: none;
            background: var(--tg-accent);
            color: white;
            font: inherit;
            font-weight: 700;
            border-radius: 18px;
            padding: 10px 16px;
            cursor: pointer;
        }

        .send-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }

        @media (max-width: 640px) {
            .feed {
                padding-left: 8px;
                padding-right: 8px;
            }

            .bubble {
                max-width: calc(100% - 44px);
            }

            .identity {
                flex-direction: column;
            }

            .composer-actions {
                align-items: flex-start;
                flex-direction: column;
            }

            .send-btn {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="app">
        <header class="topbar">
            <div class="title">
                <span class="title-dot"></span>
                <span>Комментарии</span>
            </div>
            <div class="subtitle" id="postLabel"></div>
        </header>

        <main class="feed" id="commentsList">
            <div class="welcome">Обсуждение открыто только для этого поста. Комментарии из других публикаций здесь не показываются.</div>
        </main>
    </div>

    <div class="composer">
        <div class="composer-card">
            <div class="identity">
                <input id="username" maxlength="50" placeholder="Ваше имя">
            </div>
            <textarea id="comment" maxlength="1000" placeholder="Написать комментарий..."></textarea>
            <div class="composer-actions">
                <div>
                    <div class="hint"><span id="charCount">0</span>/1000 • `Ctrl+Enter` для отправки</div>
                    <div class="status" id="status"></div>
                </div>
                <button id="submitBtn" class="send-btn" type="button">Отправить</button>
            </div>
        </div>
    </div>

    <script>
        const initialPostId = {{ post_id|tojson }};
        const initialUsername = {{ username|tojson }};
        const initialUserId = {{ user_id|tojson }};

        function resolvePostId() {
            const params = new URLSearchParams(window.location.search);
            const parts = window.location.pathname.split("/").filter(Boolean);
            if (parts[0] === "post" && parts[1]) return decodeURIComponent(parts[1]);
            return (params.get("post_id") || params.get("startapp") || initialPostId || "").trim();
        }

        const postId = resolvePostId();
        const usernameInput = document.getElementById("username");
        const commentInput = document.getElementById("comment");
        const commentsList = document.getElementById("commentsList");
        const charCount = document.getElementById("charCount");
        const status = document.getElementById("status");
        const submitBtn = document.getElementById("submitBtn");

        let userId = (initialUserId || localStorage.getItem("max_comment_user_id") || "").trim();
        if (!userId) {
            userId = "user_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
            localStorage.setItem("max_comment_user_id", userId);
        }

        let username = (initialUsername || localStorage.getItem("max_comment_username") || "").trim();
        usernameInput.value = username;
        document.getElementById("postLabel").textContent = postId
            ? "Пост: " + postId
            : "Не удалось определить пост. Откройте комментарии из кнопки под публикацией.";

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

        submitBtn.addEventListener("click", sendComment);

        function showStatus(message, type) {
            status.textContent = message;
            status.className = "status " + type;
        }

        function escapeHtml(text) {
            const div = document.createElement("div");
            div.textContent = text || "";
            return div.innerHTML;
        }

        function formatDate(value) {
            try {
                const date = new Date(value);
                return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
            } catch (error) {
                return "";
            }
        }

        function renderComments(comments) {
            const welcome = '<div class="welcome">Обсуждение открыто только для этого поста. Комментарии из других публикаций здесь не показываются.</div>';
            if (!comments.length) {
                commentsList.innerHTML = welcome + '<div class="empty">Пока нет комментариев. Можно написать первый.</div>';
                return;
            }

            commentsList.innerHTML = welcome + comments.reverse().map((comment) => {
                const mine = comment.user_id === userId;
                const initial = escapeHtml((comment.username || "?").charAt(0).toUpperCase());
                return `
                    <div class="message-row ${mine ? "mine" : ""}">
                        ${mine ? "" : `<div class="avatar">${initial}</div>`}
                        <div class="bubble">
                            <div class="message-name">${escapeHtml(comment.username)}</div>
                            <div class="message-text">${escapeHtml(comment.comment)}</div>
                            <div class="message-meta">
                                ${mine ? `<span class="message-delete" onclick="deleteComment(${comment.id})">Удалить</span>` : ""}
                                <span>${formatDate(comment.created_at)}</span>
                            </div>
                        </div>
                        ${mine ? `<div class="avatar">${initial}</div>` : ""}
                    </div>
                `;
            }).join("");

            window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
        }

        async function loadComments() {
            if (!postId) {
                commentsList.innerHTML = '<div class="empty">Нет `post_id`. Нужно открывать страницу из кнопки нужного поста.</div>';
                return;
            }

            try {
                const response = await fetch("/api/comments/" + encodeURIComponent(postId));
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Ошибка загрузки");
                renderComments(data.comments || []);
            } catch (error) {
                commentsList.innerHTML = '<div class="empty">Не удалось загрузить комментарии.</div>';
            }
        }

        async function sendComment() {
            const currentUsername = usernameInput.value.trim();
            const comment = commentInput.value.trim();

            if (!postId) {
                showStatus("Не найден post_id", "error");
                return;
            }
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
            showStatus("Отправляем...", "");

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
                if (!response.ok) throw new Error(data.error || "Ошибка отправки");

                localStorage.setItem("max_comment_username", currentUsername);
                commentInput.value = "";
                charCount.textContent = "0";
                showStatus("Комментарий отправлен", "success");
                await loadComments();
            } catch (error) {
                showStatus(error.message || "Не удалось отправить комментарий", "error");
            } finally {
                submitBtn.disabled = false;
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
                if (!response.ok) throw new Error(data.error || "Ошибка удаления");
                showStatus("Комментарий удалён", "success");
                await loadComments();
            } catch (error) {
                showStatus(error.message || "Не удалось удалить комментарий", "error");
            }
        }

        window.deleteComment = deleteComment;
        loadComments();
        setInterval(loadComments, 8000);
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    post_id = normalize_post_id(request.args.get("post_id") or request.args.get("startapp"))
    user_id = (request.args.get("user_id") or "").strip()[:128]
    username = normalize_username(request.args.get("username"))
    return render_template_string(HTML_TEMPLATE, post_id=post_id, user_id=user_id, username=username)


@app.route("/post/<path:post_id>")
def post_page(post_id):
    user_id = (request.args.get("user_id") or "").strip()[:128]
    username = normalize_username(request.args.get("username"))
    return render_template_string(
        HTML_TEMPLATE,
        post_id=normalize_post_id(post_id),
        user_id=user_id,
        username=username,
    )


@app.route("/api/comments")
def get_comments():
    try:
        post_id = require_post_id(request.args.get("post_id"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return fetch_comments(post_id)


@app.route("/api/comments/<path:post_id>")
def get_comments_by_post(post_id):
    try:
        normalized_post_id = require_post_id(post_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return fetch_comments(normalized_post_id)


def fetch_comments(post_id: str):
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
    try:
        normalized_post_id = require_post_id(post_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

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

    try:
        post_id = require_post_id(payload.get("post_id"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

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


@app.route("/api/share_link/<path:post_id>")
def share_link(post_id):
    try:
        normalized_post_id = require_post_id(post_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    base_url = request.host_url.rstrip("/")
    return jsonify(
        {
            "post_id": normalized_post_id,
            "web_app_url": f"{base_url}/post/{quote(normalized_post_id, safe='')}",
        }
    )


@app.route("/health")
def health():
    return jsonify({"status": "ok", "db_exists": os.path.exists(DB_PATH)})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
