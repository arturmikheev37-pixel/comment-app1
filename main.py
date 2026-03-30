from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import sqlite3
from urllib.parse import parse_qsl

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "comments.db")
BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "f9LHodD0cOIdrNPjh3CWiZlW8bj-DhNpjF6VBTWDQP66-wijDIChpbtLyNZeZOtubmx3thZhMxQe7j8oXnCq").strip()


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

    cursor.execute(
        """
        UPDATE comments
        SET post_id = CAST(id AS TEXT)
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
    return (raw_post_id or "").strip()[:128]


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


def parse_max_user(raw_user: str | dict | None) -> dict | None:
    if not raw_user:
        return None
    if isinstance(raw_user, dict):
        user = raw_user
    else:
        try:
            user = json.loads(raw_user)
        except json.JSONDecodeError:
            return None

    first_name = (user.get("first_name") or "").strip()
    last_name = (user.get("last_name") or "").strip()
    username = " ".join(part for part in [first_name, last_name] if part).strip()
    if not username:
        username = (user.get("username") or "Пользователь MAX").strip()

    user_id = str(user.get("user_id") or user.get("id") or "").strip()
    if not user_id:
        return None

    return {
        "user_id": user_id[:128],
        "username": username[:50] or "Пользователь MAX",
    }


def validate_max_init_data(init_data: str) -> dict | None:
    if not init_data or not BOT_TOKEN:
        return None

    pairs = parse_qsl(init_data, keep_blank_values=True)
    values = dict(pairs)
    received_hash = values.pop("hash", "")
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    return parse_max_user(values.get("user"))


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
            max-width: 460px;
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
            width: 100%;
            background: #223140;
            border-radius: 16px;
            padding: 10px 12px;
            margin-bottom: 8px;
            font-size: 14px;
        }

        textarea {
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

        textarea:focus {
            border-color: rgba(46, 166, 255, 0.7);
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
            <div class="subtitle" id="postLabel">Загрузка контекста поста...</div>
        </header>

        <main class="feed" id="commentsList">
            <div class="welcome">Мини-приложение открыто внутри MAX. Имя автора берётся из профиля MAX, а комментарии привязаны к `startapp` текущего поста.</div>
        </main>
    </div>

    <div class="composer">
        <div class="composer-card">
            <div class="identity" id="identity">Автор: определяем профиль MAX...</div>
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
        const webApp = window.WebApp || window.Maxi || null;
        const commentsList = document.getElementById("commentsList");
        const postLabel = document.getElementById("postLabel");
        const identity = document.getElementById("identity");
        const commentInput = document.getElementById("comment");
        const charCount = document.getElementById("charCount");
        const status = document.getElementById("status");
        const submitBtn = document.getElementById("submitBtn");

        let initData = "";
        let postId = "";
        let currentUser = null;

        function resolveWebAppObject() {
            if (window.WebApp) return window.WebApp;
            if (window.Telegram && window.Telegram.WebApp) return window.Telegram.WebApp;
            return window.Maxi || null;
        }

        function escapeHtml(text) {
            const div = document.createElement("div");
            div.textContent = text || "";
            return div.innerHTML;
        }

        function showStatus(message, type) {
            status.textContent = message;
            status.className = "status " + type;
        }

        function formatDate(value) {
            try {
                return new Date(value).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
            } catch (error) {
                return "";
            }
        }

        function getStartParam(appInstance) {
            if (!appInstance) return "";
            if (appInstance.initDataUnsafe && appInstance.initDataUnsafe.start_param) {
                return String(appInstance.initDataUnsafe.start_param).trim();
            }
            if (appInstance.startParam) {
                return String(appInstance.startParam).trim();
            }
            const params = new URLSearchParams(window.location.search);
            return (params.get("startapp") || params.get("post_id") || "").trim();
        }

        function getMaxUser(appInstance) {
            if (!appInstance) return null;
            const rawUser = (appInstance.initDataUnsafe && appInstance.initDataUnsafe.user) || appInstance.user || null;
            if (!rawUser) return null;

            const firstName = (rawUser.first_name || rawUser.firstName || "").trim();
            const lastName = (rawUser.last_name || rawUser.lastName || "").trim();
            const username = [firstName, lastName].filter(Boolean).join(" ").trim() || rawUser.username || "Пользователь MAX";
            const userId = String(rawUser.user_id || rawUser.id || "").trim();
            if (!userId) return null;

            return {
                user_id: userId,
                username: username
            };
        }

        async function hydrateUserFromServer() {
            if (!initData) return;
            try {
                const response = await fetch("/api/max/session", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ init_data: initData })
                });
                const data = await response.json();
                if (response.ok && data.user) {
                    currentUser = data.user;
                }
            } catch (error) {
                console.error(error);
            }
        }

        function renderComments(comments) {
            const welcome = '<div class="welcome">Это именно mini app внутри MAX. Для другого поста будет другой `startapp`, поэтому комментарии не смешиваются.</div>';
            if (!comments.length) {
                commentsList.innerHTML = welcome + '<div class="empty">Пока нет комментариев. Можно написать первый.</div>';
                return;
            }

            commentsList.innerHTML = welcome + comments.reverse().map((comment) => {
                const mine = currentUser && comment.user_id === currentUser.user_id;
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
        }

        async function loadComments() {
            if (!postId) {
                commentsList.innerHTML = '<div class="empty">Не найден `startapp` от MAX. Открывайте приложение кнопкой мини-приложения, а не прямым URL.</div>';
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
            const comment = commentInput.value.trim();

            if (!postId) {
                showStatus("MAX не передал startapp", "error");
                return;
            }
            if (!currentUser || !currentUser.user_id) {
                showStatus("Не удалось получить профиль пользователя из MAX", "error");
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
                        user_id: currentUser.user_id,
                        username: currentUser.username,
                        comment: comment,
                        init_data: initData
                    })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Ошибка отправки");
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
            if (!currentUser) return;
            try {
                const response = await fetch("/api/comment/" + commentId, {
                    method: "DELETE",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: currentUser.user_id })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Ошибка удаления");
                showStatus("Комментарий удалён", "success");
                await loadComments();
            } catch (error) {
                showStatus(error.message || "Не удалось удалить комментарий", "error");
            }
        }

        async function boot() {
            const appInstance = resolveWebAppObject();
            if (appInstance && typeof appInstance.ready === "function") {
                appInstance.ready();
            }
            if (appInstance && typeof appInstance.expand === "function") {
                appInstance.expand();
            }

            initData = (appInstance && appInstance.initData) || "";
            postId = getStartParam(appInstance);
            currentUser = getMaxUser(appInstance);
            await hydrateUserFromServer();

            postLabel.textContent = postId
                ? "Пост: " + postId
                : "Нет startapp. Если страница открыта как обычный URL, MAX данные не передаст.";

            identity.textContent = currentUser
                ? "Автор: " + currentUser.username
                : "Автор: профиль MAX не найден";

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

            await loadComments();
            setInterval(loadComments, 8000);
        }

        window.deleteComment = deleteComment;
        boot();
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/max/session", methods=["POST"])
def get_max_session():
    payload = request.get_json(silent=True) or {}
    user = validate_max_init_data(payload.get("init_data", ""))
    if not user:
        return jsonify({"error": "Не удалось проверить initData MAX"}), 400
    return jsonify({"user": user})


@app.route("/api/comments/<path:post_id>")
def get_comments_by_post(post_id):
    normalized_post_id = normalize_post_id(post_id)
    if not normalized_post_id:
        return jsonify({"error": "Не передан post_id"}), 400

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, post_id, user_id, username, comment, created_at
        FROM comments
        WHERE post_id = ?
        ORDER BY created_at DESC
        """,
        (normalized_post_id,),
    ).fetchall()
    conn.close()
    return jsonify({"post_id": normalized_post_id, "comments": [serialize_comment(row) for row in rows]})


@app.route("/api/post_count/<path:post_id>")
def get_post_count(post_id):
    normalized_post_id = normalize_post_id(post_id)
    if not normalized_post_id:
        return jsonify({"error": "Не передан post_id"}), 400

    conn = get_db_connection()
    row = conn.execute("SELECT COUNT(*) AS count FROM comments WHERE post_id = ?", (normalized_post_id,)).fetchone()
    conn.close()
    return jsonify({"post_id": normalized_post_id, "count": row["count"]})


@app.route("/api/comment", methods=["POST"])
def add_comment():
    payload = request.get_json(silent=True) or {}
    post_id = normalize_post_id(payload.get("post_id"))
    comment = normalize_comment(payload.get("comment"))
    verified_user = validate_max_init_data(payload.get("init_data", ""))

    if not post_id:
        return jsonify({"error": "Не передан post_id"}), 400
    if not verified_user:
        return jsonify({"error": "Не удалось подтвердить пользователя MAX"}), 400
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
        (post_id, verified_user["user_id"], verified_user["username"], comment, created_at),
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
                "user_id": verified_user["user_id"],
                "username": verified_user["username"],
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


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
