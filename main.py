from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from urllib.parse import parse_qsl

from flask import Flask, jsonify, render_template_string, request, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "comments.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "f9LHodD0cOIdrNPjh3CWiZlW8bj-DhNpjF6VBTWDQP66-wijDIChpbtLyNZeZOtubmx3thZhMxQe7j8oXnCq").strip()
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
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
            image_path TEXT,
            parent_id INTEGER,
            edited_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            post_id TEXT PRIMARY KEY,
            source_post_id TEXT,
            post_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS comment_reactions (
            comment_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            reaction TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (comment_id, user_id, reaction)
        )
        """
    )

    columns = {row["name"] for row in cursor.execute("PRAGMA table_info(comments)").fetchall()}
    if "post_id" not in columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN post_id TEXT")
    if "image_path" not in columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN image_path TEXT")
    if "parent_id" not in columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN parent_id INTEGER")
    if "edited_at" not in columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN edited_at TEXT")

    post_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(posts)").fetchall()}
    if "source_post_id" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN source_post_id TEXT")
    if "post_text" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN post_text TEXT NOT NULL DEFAULT ''")
    if "created_at" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")

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


def build_file_url(image_path: str | None) -> str | None:
    if not image_path:
        return None
    return f"/uploads/{image_path}"


def serialize_comment(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "post_id": row["post_id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "comment": row["comment"],
        "image_url": build_file_url(row["image_path"]),
        "parent_id": row["parent_id"],
        "edited_at": row["edited_at"],
        "created_at": row["created_at"],
    }


def serialize_post(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    return {
        "post_id": row["post_id"],
        "source_post_id": row["source_post_id"],
        "post_text": row["post_text"],
        "created_at": row["created_at"],
    }


def get_post_info(post_id: str) -> dict | None:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT post_id, source_post_id, post_text, created_at FROM posts WHERE post_id = ?",
        (post_id,),
    ).fetchone()
    conn.close()
    return serialize_post(row)


def get_reactions_map(post_id: str) -> dict[int, dict]:
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT r.comment_id, r.reaction, r.user_id
        FROM comment_reactions r
        JOIN comments c ON c.id = r.comment_id
        WHERE c.post_id = ?
        """,
        (post_id,),
    ).fetchall()
    conn.close()

    result: dict[int, dict] = {}
    for row in rows:
        comment_bucket = result.setdefault(row["comment_id"], {"counts": {}, "users": {}})
        comment_bucket["counts"][row["reaction"]] = comment_bucket["counts"].get(row["reaction"], 0) + 1
        comment_bucket["users"].setdefault(row["reaction"], []).append(row["user_id"])
    return result


def allowed_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


def save_uploaded_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    filename = secure_filename(file_storage.filename)
    if not filename or not allowed_file(filename):
        raise ValueError("Можно загружать только JPG, PNG, GIF или WEBP")
    _, ext = os.path.splitext(filename)
    stored_name = f"{uuid.uuid4().hex}{ext.lower()}"
    file_storage.save(os.path.join(UPLOAD_DIR, stored_name))
    return stored_name


def parse_request_payload():
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        return request.form, request.files
    return request.get_json(silent=True) or {}, {}


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
            display: none;
        }

        .post-card {
            margin: 12px;
            padding: 12px 14px;
            border-radius: 18px;
            background: rgba(23, 33, 43, 0.94);
            border: 1px solid var(--tg-panel-border);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.14);
        }

        .post-card-label {
            font-size: 11px;
            color: var(--tg-muted);
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .post-card-text {
            font-size: 14px;
            line-height: 1.45;
            color: var(--tg-text);
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .feed {
            flex: 1;
            padding: 4px 12px 110px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .message-row {
            display: flex;
            gap: 8px;
            align-items: flex-end;
        }

        .message-thread {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .message-thread.reply {
            margin-left: 44px;
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

        .message-image {
            display: block;
            margin-top: 8px;
            max-width: min(100%, 320px);
            border-radius: 14px;
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

        .message-action {
            cursor: pointer;
            color: #d7e9ff;
        }

        .reply-pill {
            margin-bottom: 6px;
            padding: 6px 8px;
            border-left: 2px solid #59aef9;
            background: rgba(255, 255, 255, 0.04);
            border-radius: 10px;
            font-size: 12px;
            color: #c9def2;
        }

        .reactions {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            margin-top: 8px;
        }

        .reaction-chip {
            background: rgba(255, 255, 255, 0.06);
            color: #d7e9ff;
            border-radius: 999px;
            padding: 4px 8px;
            font-size: 12px;
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
            padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
            background: linear-gradient(to top, rgba(14, 22, 33, 0.98), rgba(14, 22, 33, 0.74));
        }

        .composer-card {
            background: rgba(23, 33, 43, 0.96);
            border: 1px solid var(--tg-panel-border);
            border-radius: 20px;
            padding: 8px;
            box-shadow: 0 12px 34px rgba(0, 0, 0, 0.28);
        }

        .identity {
            width: 100%;
            background: #223140;
            border-radius: 14px;
            padding: 8px 10px;
            margin-bottom: 6px;
            font-size: 12px;
        }

        .reply-box {
            display: none;
            margin-bottom: 8px;
            padding: 10px 12px;
            border-radius: 14px;
            background: #223140;
            font-size: 12px;
            color: #cfe5fb;
        }

        .reply-box.show {
            display: block;
        }

        .reaction-menu {
            position: fixed;
            z-index: 30;
            display: none;
            gap: 8px;
            padding: 8px;
            border-radius: 18px;
            background: rgba(23, 33, 43, 0.98);
            border: 1px solid var(--tg-panel-border);
            box-shadow: 0 14px 34px rgba(0, 0, 0, 0.28);
        }

        .reaction-menu.show {
            display: flex;
        }

        .reaction-menu button {
            border: none;
            background: transparent;
            color: white;
            font-size: 22px;
            cursor: pointer;
            padding: 4px 6px;
            border-radius: 12px;
        }

        .reaction-menu button:hover {
            background: rgba(255, 255, 255, 0.08);
        }

        .attachment-row {
            margin-top: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
            justify-content: space-between;
        }

        .attach-btn {
            border: none;
            background: #223140;
            color: #d7e9ff;
            font: inherit;
            border-radius: 14px;
            padding: 8px 12px;
            cursor: pointer;
        }

        .preview {
            margin-top: 8px;
            display: none;
        }

        .preview.show {
            display: block;
        }

        .preview img {
            max-width: 160px;
            border-radius: 12px;
            display: block;
        }

        .preview-actions {
            margin-top: 6px;
            display: flex;
            gap: 8px;
        }

        textarea {
            width: 100%;
            min-height: 44px;
            max-height: 120px;
            resize: vertical;
            background: #223140;
            border: 1px solid transparent;
            color: white;
            border-radius: 16px;
            padding: 10px 12px;
            outline: none;
            font: inherit;
            font-size: 14px;
            line-height: 1.35;
        }

        textarea:focus {
            border-color: rgba(46, 166, 255, 0.7);
        }

        .composer-actions {
            margin-top: 6px;
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
            border-radius: 16px;
            padding: 8px 14px;
            cursor: pointer;
        }

        .action-menu {
            position: fixed;
            z-index: 31;
            display: none;
            min-width: 160px;
            padding: 6px;
            border-radius: 16px;
            background: rgba(23, 33, 43, 0.99);
            border: 1px solid var(--tg-panel-border);
            box-shadow: 0 14px 34px rgba(0, 0, 0, 0.28);
        }

        .action-menu.show {
            display: block;
        }

        .action-menu button {
            width: 100%;
            text-align: left;
            border: none;
            background: transparent;
            color: #ffffff;
            font: inherit;
            padding: 10px 12px;
            border-radius: 12px;
            cursor: pointer;
        }

        .action-menu button:hover {
            background: rgba(255, 255, 255, 0.08);
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
        <section class="post-card" id="postCard" hidden>
            <div class="post-card-label">Пост</div>
            <div class="post-card-text" id="postCardText"></div>
        </section>

        <main class="feed" id="commentsList"></main>
    </div>

    <div class="composer">
        <div class="composer-card">
            <div class="identity" id="identity">Автор: определяем профиль MAX...</div>
            <div class="reply-box" id="replyBox"></div>
            <textarea id="comment" maxlength="1000" placeholder="Написать комментарий..."></textarea>
            <div class="attachment-row">
                <button class="attach-btn" id="attachBtn" type="button">Фото</button>
                <input id="imageInput" type="file" accept="image/*" hidden>
            </div>
            <div class="preview" id="imagePreview">
                <img id="previewImage" alt="preview">
                <div class="preview-actions">
                    <button class="attach-btn" id="removeImageBtn" type="button">Убрать фото</button>
                </div>
            </div>
            <div class="composer-actions">
                <div>
                    <div class="hint"><span id="charCount">0</span>/1000 • можно текст, эмодзи и фото</div>
                    <div class="status" id="status"></div>
                </div>
                <button id="submitBtn" class="send-btn" type="button">Отправить</button>
            </div>
        </div>
    </div>
    <div class="reaction-menu" id="reactionMenu"></div>
    <div class="action-menu" id="actionMenu"></div>

    <script src="https://st.max.ru/js/max-web-app.js"></script>
    <script>
        const commentsList = document.getElementById("commentsList");
        const postLabel = document.getElementById("postLabel");
        const identity = document.getElementById("identity");
        const commentInput = document.getElementById("comment");
        const charCount = document.getElementById("charCount");
        const status = document.getElementById("status");
        const submitBtn = document.getElementById("submitBtn");
        const attachBtn = document.getElementById("attachBtn");
        const imageInput = document.getElementById("imageInput");
        const imagePreview = document.getElementById("imagePreview");
        const previewImage = document.getElementById("previewImage");
        const removeImageBtn = document.getElementById("removeImageBtn");
        const postCard = document.getElementById("postCard");
        const postCardText = document.getElementById("postCardText");
        const replyBox = document.getElementById("replyBox");
        const reactionMenu = document.getElementById("reactionMenu");
        const actionMenu = document.getElementById("actionMenu");

        let initData = "";
        let postId = "";
        let currentUser = null;
        let selectedImage = null;
        let editingCommentId = null;
        let latestComments = [];
        let replyToCommentId = null;
        let postInfo = null;
        const reactionOptions = ["👍", "❤️", "🔥", "😂"];
        let reactionMenuCommentId = null;
        let actionMenuCommentId = null;
        let longPressTimer = null;

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
            return (params.get("WebAppStartParam") || params.get("startapp") || params.get("post_id") || "").trim();
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

            return { user_id: userId, username: username };
        }

        function getInitDataFallback(appInstance) {
            if (appInstance && appInstance.initData) {
                return String(appInstance.initData);
            }
            const params = new URLSearchParams(window.location.search);
            return (params.get("WebAppData") || params.get("initData") || "").trim();
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

        function setPreviewFromFile(file) {
            if (!file) {
                imagePreview.classList.remove("show");
                previewImage.removeAttribute("src");
                return;
            }
            const reader = new FileReader();
            reader.onload = () => {
                previewImage.src = reader.result;
                imagePreview.classList.add("show");
            };
            reader.readAsDataURL(file);
        }

        function resetComposer() {
            editingCommentId = null;
            replyToCommentId = null;
            selectedImage = null;
            commentInput.value = "";
            charCount.textContent = "0";
            imageInput.value = "";
            imagePreview.classList.remove("show");
            previewImage.removeAttribute("src");
            submitBtn.textContent = "Отправить";
            replyBox.classList.remove("show");
            replyBox.textContent = "";
        }

        function renderReactionButtons(comment) {
            const reactions = comment.reactions || {};
            return Object.entries(reactions).map(([emoji, count]) => {
                return `<span class="reaction-chip">${emoji} ${count}</span>`;
            }).join("");
        }

        function renderCommentNode(comment, replyMap) {
            const mine = currentUser && comment.user_id === currentUser.user_id;
            const initial = escapeHtml((comment.username || "?").charAt(0).toUpperCase());
            const imageHtml = comment.image_url ? `<img class="message-image" src="${comment.image_url}" alt="comment image">` : "";
            const editedHtml = comment.edited_at ? '<span>изменено</span>' : "";
            const parentPreview = comment.parent_preview ? `<div class="reply-pill">Ответ для ${escapeHtml(comment.parent_preview.username)}: ${escapeHtml(comment.parent_preview.comment)}</div>` : "";
            const replies = (replyMap[comment.id] || []).map((child) => `<div class="message-thread reply">${renderCommentNode(child, replyMap)}</div>`).join("");
            return `
                <div class="message-thread">
                    <div class="message-row ${mine ? "mine" : ""}">
                        ${mine ? "" : `<div class="avatar">${initial}</div>`}
                        <div class="bubble" data-comment-id="${comment.id}">
                            <div class="message-name">${escapeHtml(comment.username)}</div>
                            ${parentPreview}
                            <div class="message-text">${escapeHtml(comment.comment)}</div>
                            ${imageHtml}
                            <div class="reactions">${renderReactionButtons(comment)}</div>
                            <div class="message-meta">
                                ${editedHtml}
                                <span>${formatDate(comment.edited_at || comment.created_at)}</span>
                            </div>
                        </div>
                        ${mine ? `<div class="avatar">${initial}</div>` : ""}
                    </div>
                    ${replies}
                </div>
            `;
        }

        function renderComments(comments) {
            latestComments = comments || [];
            if (!latestComments.length) {
                commentsList.innerHTML = '<div class="empty">Пока нет комментариев. Можно написать первый.</div>';
                return;
            }
            const sorted = [...latestComments].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
            const replyMap = {};
            const roots = [];
            sorted.forEach((comment) => {
                if (comment.parent_id) {
                    if (!replyMap[comment.parent_id]) replyMap[comment.parent_id] = [];
                    replyMap[comment.parent_id].push(comment);
                } else {
                    roots.push(comment);
                }
            });

            commentsList.innerHTML = roots.map((comment) => renderCommentNode(comment, replyMap)).join("");
        }

        async function loadComments() {
            if (!postId) {
                commentsList.innerHTML = '<div class="empty">Не найден startapp для этого поста.</div>';
                return;
            }

            try {
                const url = new URL("/api/comments/" + encodeURIComponent(postId), window.location.origin);
                if (initData) {
                    url.searchParams.set("init_data", initData);
                }
                const response = await fetch(url);
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Ошибка загрузки");
                postInfo = data.post || null;
                if (postInfo && postInfo.post_text) {
                    postCard.hidden = false;
                    postCardText.textContent = postInfo.post_text;
                } else {
                    postCard.hidden = true;
                }
                renderComments(data.comments || []);
                bindLongPressHandlers();
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
            if (!comment && !selectedImage && !editingCommentId) {
                showStatus("Введите комментарий или выберите фото", "error");
                commentInput.focus();
                return;
            }

            submitBtn.disabled = true;
            showStatus(editingCommentId ? "Сохраняем..." : "Отправляем...", "");

            try {
                let response;
                if (editingCommentId) {
                    response = await fetch("/api/comment/" + editingCommentId, {
                        method: "PUT",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ comment: comment, init_data: initData })
                    });
                } else {
                    const formData = new FormData();
                    formData.append("post_id", postId);
                    formData.append("comment", comment);
                    formData.append("init_data", initData);
                    if (replyToCommentId) formData.append("parent_id", String(replyToCommentId));
                    if (selectedImage) formData.append("image", selectedImage);
                    response = await fetch("/api/comment", { method: "POST", body: formData });
                }

                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Ошибка отправки");
                const wasEditing = Boolean(editingCommentId);
                resetComposer();
                showStatus(wasEditing ? "Комментарий обновлён" : "Комментарий отправлен", "success");
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
                    body: JSON.stringify({ init_data: initData, user_id: currentUser.user_id })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Ошибка удаления");
                showStatus("Комментарий удалён", "success");
                await loadComments();
            } catch (error) {
                showStatus(error.message || "Не удалось удалить комментарий", "error");
            }
        }

        function startEdit(commentId) {
            const comment = latestComments.find((item) => item.id === commentId);
            if (!comment) return;
            editingCommentId = commentId;
            replyToCommentId = null;
            commentInput.value = comment.comment || "";
            charCount.textContent = commentInput.value.length;
            submitBtn.textContent = "Сохранить";
            commentInput.focus();
            replyBox.classList.remove("show");
            showStatus("Редактирование комментария", "");
        }

        function startReply(commentId) {
            const comment = latestComments.find((item) => item.id === commentId);
            if (!comment) return;
            editingCommentId = null;
            replyToCommentId = commentId;
            submitBtn.textContent = "Отправить";
            replyBox.classList.add("show");
            replyBox.textContent = `Ответ для ${comment.username}: ${comment.comment || "фото"}`;
            commentInput.focus();
        }

        async function toggleReaction(commentId, reaction) {
            if (!initData) return;
            try {
                const response = await fetch("/api/comment/" + commentId + "/reaction", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ init_data: initData, reaction: reaction })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Ошибка реакции");
                await loadComments();
            } catch (error) {
                showStatus(error.message || "Не удалось поставить реакцию", "error");
            }
        }

        function openReactionMenu(commentId, targetElement) {
            reactionMenuCommentId = commentId;
            reactionMenu.innerHTML = reactionOptions.map((emoji) => {
                return `<button type="button" onclick="pickReaction(${JSON.stringify(emoji)})">${emoji}</button>`;
            }).join("");
            const rect = targetElement.getBoundingClientRect();
            reactionMenu.style.left = Math.max(8, rect.left) + "px";
            reactionMenu.style.top = Math.max(8, rect.top - 58) + "px";
            reactionMenu.classList.add("show");
        }

        function closeReactionMenu() {
            reactionMenu.classList.remove("show");
            reactionMenuCommentId = null;
        }

        function openActionMenu(commentId, targetElement) {
            const comment = latestComments.find((item) => item.id === commentId);
            if (!comment) return;
            actionMenuCommentId = commentId;
            const isMine = currentUser && comment.user_id === currentUser.user_id;
            actionMenu.innerHTML = `
                <button type="button" onclick="menuReply()">Ответить</button>
                ${isMine ? '<button type="button" onclick="menuEdit()">Редактировать</button>' : ''}
                ${isMine ? '<button type="button" onclick="menuDelete()">Удалить</button>' : ''}
            `;
            const rect = targetElement.getBoundingClientRect();
            actionMenu.style.left = Math.max(8, rect.left) + "px";
            actionMenu.style.top = Math.min(window.innerHeight - 180, rect.bottom + 8) + "px";
            actionMenu.classList.add("show");
        }

        function closeActionMenu() {
            actionMenu.classList.remove("show");
            actionMenuCommentId = null;
        }

        function bindLongPressHandlers() {
            document.querySelectorAll(".bubble[data-comment-id]").forEach((bubble) => {
                const commentId = Number(bubble.dataset.commentId);
                const start = (event) => {
                    if (event.target.closest(".message-action, .message-delete")) return;
                    clearTimeout(longPressTimer);
                    longPressTimer = setTimeout(() => openReactionMenu(commentId, bubble), 450);
                };
                const clickOpen = (event) => {
                    if (event.target.closest(".message-action, .message-delete")) return;
                    closeReactionMenu();
                    openActionMenu(commentId, bubble);
                };
                const cancel = () => {
                    clearTimeout(longPressTimer);
                };
                bubble.onmousedown = start;
                bubble.ontouchstart = start;
                bubble.onclick = clickOpen;
                bubble.onmouseup = cancel;
                bubble.onmouseleave = cancel;
                bubble.ontouchend = cancel;
                bubble.ontouchcancel = cancel;
            });
        }

        async function pickReaction(reaction) {
            if (!reactionMenuCommentId) return;
            closeReactionMenu();
            await toggleReaction(reactionMenuCommentId, reaction);
        }

        function menuReply() {
            if (!actionMenuCommentId) return;
            const id = actionMenuCommentId;
            closeActionMenu();
            startReply(id);
        }

        function menuEdit() {
            if (!actionMenuCommentId) return;
            const id = actionMenuCommentId;
            closeActionMenu();
            startEdit(id);
        }

        async function menuDelete() {
            if (!actionMenuCommentId) return;
            const id = actionMenuCommentId;
            closeActionMenu();
            await deleteComment(id);
        }

        async function boot() {
            const appInstance = resolveWebAppObject();
            if (appInstance && typeof appInstance.ready === "function") appInstance.ready();
            if (appInstance && typeof appInstance.expand === "function") appInstance.expand();

            initData = getInitDataFallback(appInstance);
            postId = getStartParam(appInstance);
            currentUser = getMaxUser(appInstance);
            await hydrateUserFromServer();

            postLabel.textContent = postId ? "Пост: " + postId : "";
            postLabel.textContent = "";
            identity.textContent = currentUser ? "Автор: " + currentUser.username : "Автор: профиль MAX не найден";

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
            attachBtn.addEventListener("click", () => imageInput.click());
            imageInput.addEventListener("change", () => {
                selectedImage = imageInput.files && imageInput.files[0] ? imageInput.files[0] : null;
                setPreviewFromFile(selectedImage);
            });
            removeImageBtn.addEventListener("click", () => {
                selectedImage = null;
                imageInput.value = "";
                setPreviewFromFile(null);
            });
            document.addEventListener("click", (event) => {
                if (!reactionMenu.contains(event.target)) {
                    closeReactionMenu();
                }
                if (!actionMenu.contains(event.target)) {
                    closeActionMenu();
                }
            });

            await loadComments();
            setInterval(loadComments, 8000);
        }

        window.deleteComment = deleteComment;
        window.startEdit = startEdit;
        window.startReply = startReply;
        window.toggleReaction = toggleReaction;
        window.pickReaction = pickReaction;
        window.menuReply = menuReply;
        window.menuEdit = menuEdit;
        window.menuDelete = menuDelete;
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
        SELECT id, post_id, user_id, username, comment, image_path, parent_id, edited_at, created_at
        FROM comments
        WHERE post_id = ?
        ORDER BY created_at DESC
        """,
        (normalized_post_id,),
    ).fetchall()
    conn.close()
    comments = [serialize_comment(row) for row in rows]
    reactions_map = get_reactions_map(normalized_post_id)
    comment_lookup = {comment["id"]: comment for comment in comments}
    current_user = validate_max_init_data(request.args.get("init_data", ""))
    current_user_id = (current_user or {}).get("user_id")

    for comment in comments:
        reaction_meta = reactions_map.get(comment["id"], {"counts": {}, "users": {}})
        comment["reactions"] = reaction_meta["counts"]
        comment["my_reactions"] = [
            emoji for emoji, users in reaction_meta["users"].items()
            if current_user_id and current_user_id in users
        ]
        if comment["parent_id"] and comment["parent_id"] in comment_lookup:
            parent = comment_lookup[comment["parent_id"]]
            comment["parent_preview"] = {
                "username": parent["username"],
                "comment": (parent["comment"] or "Фото")[:80],
            }
        else:
            comment["parent_preview"] = None
    return jsonify({"post_id": normalized_post_id, "post": get_post_info(normalized_post_id), "comments": comments})


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
    payload, files = parse_request_payload()
    post_id = normalize_post_id(payload.get("post_id"))
    comment = normalize_comment(payload.get("comment"))
    parent_id = payload.get("parent_id")
    verified_user = validate_max_init_data(payload.get("init_data", ""))

    if not post_id:
        return jsonify({"error": "Не передан post_id"}), 400
    if not verified_user:
        return jsonify({"error": "Не удалось подтвердить пользователя MAX"}), 400
    try:
        image_path = save_uploaded_image(files.get("image")) if files else None
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if not comment and not image_path:
        return jsonify({"error": "Комментарий пустой"}), 400
    normalized_parent_id = int(parent_id) if str(parent_id or "").isdigit() else None

    created_at = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO comments (post_id, user_id, username, comment, image_path, parent_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (post_id, verified_user["user_id"], verified_user["username"], comment, image_path, normalized_parent_id, created_at),
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
                "image_url": build_file_url(image_path),
                "parent_id": normalized_parent_id,
                "edited_at": None,
                "created_at": created_at,
            },
        }
    )


@app.route("/api/comment/<int:comment_id>", methods=["PUT"])
def edit_comment(comment_id):
    payload = request.get_json(silent=True) or {}
    comment = normalize_comment(payload.get("comment"))
    verified_user = validate_max_init_data(payload.get("init_data", ""))

    if not verified_user:
        return jsonify({"error": "Не удалось подтвердить пользователя MAX"}), 400

    conn = get_db_connection()
    row = conn.execute(
        "SELECT id, image_path FROM comments WHERE id = ? AND user_id = ?",
        (comment_id, verified_user["user_id"]),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Комментарий не найден или нет прав"}), 404
    if not comment and not row["image_path"]:
        conn.close()
        return jsonify({"error": "Комментарий пустой"}), 400

    edited_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE comments SET comment = ?, edited_at = ? WHERE id = ?",
        (comment, edited_at, comment_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "edited_at": edited_at})


@app.route("/api/comment/<int:comment_id>", methods=["DELETE"])
def delete_comment(comment_id):
    payload = request.get_json(silent=True) or {}
    verified_user = validate_max_init_data(payload.get("init_data", ""))
    user_id = (verified_user or {}).get("user_id") or (payload.get("user_id") or "").strip()[:128]

    if not user_id:
        return jsonify({"error": "Не передан user_id"}), 400

    conn = get_db_connection()
    row = conn.execute("SELECT image_path FROM comments WHERE id = ? AND user_id = ?", (comment_id, user_id)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Комментарий не найден или нет прав"}), 404

    cursor = conn.cursor()
    cursor.execute("DELETE FROM comments WHERE id = ? AND user_id = ?", (comment_id, user_id))
    conn.commit()
    conn.close()

    image_path = row["image_path"]
    if image_path:
        image_file = os.path.join(UPLOAD_DIR, image_path)
        if os.path.exists(image_file):
            os.remove(image_file)
    return jsonify({"status": "success"})


@app.route("/api/comment/<int:comment_id>/reaction", methods=["POST"])
def toggle_comment_reaction(comment_id):
    payload = request.get_json(silent=True) or {}
    verified_user = validate_max_init_data(payload.get("init_data", ""))
    reaction = (payload.get("reaction") or "").strip()[:8]

    if not verified_user:
        return jsonify({"error": "Не удалось подтвердить пользователя MAX"}), 400
    if not reaction:
        return jsonify({"error": "Недопустимая реакция"}), 400

    conn = get_db_connection()
    comment = conn.execute("SELECT id FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if not comment:
        conn.close()
        return jsonify({"error": "Комментарий не найден"}), 404

    exists = conn.execute(
        "SELECT 1 FROM comment_reactions WHERE comment_id = ? AND user_id = ? AND reaction = ?",
        (comment_id, verified_user["user_id"], reaction),
    ).fetchone()
    if exists:
        conn.execute(
            "DELETE FROM comment_reactions WHERE comment_id = ? AND user_id = ? AND reaction = ?",
            (comment_id, verified_user["user_id"], reaction),
        )
        active = False
    else:
        conn.execute(
            """
            INSERT INTO comment_reactions (comment_id, user_id, reaction, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (comment_id, verified_user["user_id"], reaction, datetime.now(timezone.utc).isoformat()),
        )
        active = True
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "active": active})


@app.route("/api/post", methods=["POST"])
def register_post():
    payload = request.get_json(silent=True) or {}
    post_id = normalize_post_id(payload.get("post_id"))
    source_post_id = str(payload.get("source_post_id") or "").strip()[:256]
    post_text = (payload.get("post_text") or "").strip()[:4000]

    if not post_id or not post_text:
        return jsonify({"error": "Не переданы данные поста"}), 400

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO posts (post_id, source_post_id, post_text, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            source_post_id = excluded.source_post_id,
            post_text = excluded.post_text
        """,
        (post_id, source_post_id, post_text, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "db_exists": os.path.exists(DB_PATH)})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
