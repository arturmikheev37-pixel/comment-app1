import base64
from datetime import datetime, timedelta, timezone
import hmac
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from urllib.parse import parse_qsl, quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, render_template_string, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)
DEFAULT_DATA_ROOT = os.getenv("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")


def resolve_data_dir() -> str:
    candidates = []
    configured = (os.getenv("COMMENTS_DATA_DIR") or "").strip()
    if configured:
        candidates.append(configured)
    candidates.append(os.path.join(DEFAULT_DATA_ROOT, "MAXCommentBotData"))
    candidates.append(os.path.join(BASE_DIR, "persistent_data"))
    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            continue
    return os.path.join(BASE_DIR, "persistent_data")


DATA_DIR = resolve_data_dir()
LEGACY_DB_PATH = os.path.join(BASE_DIR, "comments.db")
LEGACY_STORE_DB_PATH = os.path.join(BASE_DIR, "comment_store.db")
LEGACY_UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
LEGACY_BACKUP_DIR = os.path.join(BASE_DIR, "backups")
LEGACY_STORE_ARCHIVE_PATH = os.path.join(BASE_DIR, "comment_store.zip")
DB_PATH = os.path.join(DATA_DIR, "comments.db")
STORE_DB_PATH = os.getenv("COMMENTS_STORE_DB", os.path.join(DATA_DIR, "comment_store.db"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
BACKUP_DIR = os.getenv("COMMENTS_BACKUP_DIR", os.path.join(DATA_DIR, "backups"))
BACKUP_RETENTION = max(3, int(os.getenv("COMMENTS_BACKUP_RETENTION", "20")))
STORE_ARCHIVE_PATH = os.getenv("COMMENTS_STORE_ARCHIVE", os.path.join(DATA_DIR, "comment_store.zip"))
BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "f9LHodD0cOIdrNPjh3CWiZlW8bj-DhNpjF6VBTWDQP66-wijDIChpbtLyNZeZOtubmx3thZhMxQe7j8oXnCq").strip()
BOT_USERNAME = os.getenv("MAX_BOT_USERNAME", "id250300578953_1_bot").strip()
DEFAULT_SYNC_SECRET = "my-super-sync-key-2026"
SYNC_SECRET = (os.getenv("MAX_SYNC_SECRET") or DEFAULT_SYNC_SECRET).strip()
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_VIDEO_BYTES = 80 * 1024 * 1024
BACKUP_LOCK = threading.RLock()
app.config["MAX_CONTENT_LENGTH"] = MAX_VIDEO_BYTES + (2 * 1024 * 1024)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def migrate_legacy_storage():
    os.makedirs(DATA_DIR, exist_ok=True)

    def db_row_count(path: str) -> int:
        if not os.path.exists(path):
            return 0
        try:
            conn = sqlite3.connect(path)
            row = conn.execute("SELECT COUNT(*) FROM comments").fetchone()
            conn.close()
            return int(row[0] if row else 0)
        except sqlite3.Error:
            return 0

    migrations = [
        (LEGACY_DB_PATH, DB_PATH),
        (LEGACY_STORE_DB_PATH, STORE_DB_PATH),
        (LEGACY_STORE_ARCHIVE_PATH, STORE_ARCHIVE_PATH),
    ]
    for source, target in migrations:
        source_exists = os.path.exists(source)
        target_exists = os.path.exists(target)
        if not source_exists:
            continue
        if source.endswith(".db"):
            source_count = db_row_count(source)
            target_count = db_row_count(target)
            should_replace = (not target_exists) or (source_count > 0 and target_count == 0)
        else:
            source_size = os.path.getsize(source) if source_exists else 0
            target_size = os.path.getsize(target) if target_exists else 0
            should_replace = (not target_exists) or (source_size > target_size)
        if should_replace:
            try:
                os.replace(source, target)
            except OSError:
                pass

    if os.path.isdir(LEGACY_UPLOAD_DIR) and not os.path.isdir(UPLOAD_DIR):
        try:
            os.replace(LEGACY_UPLOAD_DIR, UPLOAD_DIR)
        except OSError:
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            for root, _, files in os.walk(LEGACY_UPLOAD_DIR):
                rel_root = os.path.relpath(root, LEGACY_UPLOAD_DIR)
                target_root = UPLOAD_DIR if rel_root == "." else os.path.join(UPLOAD_DIR, rel_root)
                os.makedirs(target_root, exist_ok=True)
                for file_name in files:
                    source_file = os.path.join(root, file_name)
                    target_file = os.path.join(target_root, file_name)
                    if not os.path.exists(target_file):
                        try:
                            os.replace(source_file, target_file)
                        except OSError:
                            pass

    if os.path.isdir(LEGACY_BACKUP_DIR) and not os.path.isdir(BACKUP_DIR):
        try:
            os.replace(LEGACY_BACKUP_DIR, BACKUP_DIR)
        except OSError:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            for file_name in os.listdir(LEGACY_BACKUP_DIR):
                source_file = os.path.join(LEGACY_BACKUP_DIR, file_name)
                target_file = os.path.join(BACKUP_DIR, file_name)
                if os.path.isfile(source_file) and not os.path.exists(target_file):
                    try:
                        os.replace(source_file, target_file)
                    except OSError:
                        pass


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            post_id TEXT PRIMARY KEY,
            source_post_id TEXT,
            source_chat_id TEXT,
            button_message_id TEXT,
            counter_enabled INTEGER NOT NULL DEFAULT 1,
            post_text TEXT NOT NULL DEFAULT '',
            message_text TEXT NOT NULL DEFAULT '',
            attachments_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            author_type TEXT NOT NULL DEFAULT 'user',
            channel_chat_id TEXT,
            public_username TEXT,
            avatar_url TEXT,
            comment TEXT NOT NULL DEFAULT '',
            image_path TEXT,
            media_path TEXT,
            media_type TEXT,
            parent_id INTEGER,
            edited_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            public_username TEXT,
            avatar_url TEXT,
            notifications_enabled INTEGER NOT NULL DEFAULT 1,
            consent_accepted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS channels (
            chat_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            avatar_url TEXT NOT NULL DEFAULT '',
            owner_user_id TEXT NOT NULL DEFAULT '',
            owner_username TEXT NOT NULL DEFAULT '',
            is_blocked INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )

    comment_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(comments)").fetchall()}
    if "image_path" not in comment_columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN image_path TEXT")
    if "public_username" not in comment_columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN public_username TEXT")
    if "author_type" not in comment_columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN author_type TEXT NOT NULL DEFAULT 'user'")
    if "channel_chat_id" not in comment_columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN channel_chat_id TEXT")
    if "avatar_url" not in comment_columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN avatar_url TEXT")
    if "media_path" not in comment_columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN media_path TEXT")
    if "media_type" not in comment_columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN media_type TEXT")
    if "parent_id" not in comment_columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN parent_id INTEGER")
    if "edited_at" not in comment_columns:
        cursor.execute("ALTER TABLE comments ADD COLUMN edited_at TEXT")

    post_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(posts)").fetchall()}
    user_settings_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(user_settings)").fetchall()}
    channel_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(channels)").fetchall()}
    if "channel_id" in channel_columns and "chat_id" not in channel_columns:
        title_expr = "COALESCE(channel_name, '')" if "channel_name" in channel_columns else "''"
        avatar_expr = "COALESCE(avatar_url, '')" if "avatar_url" in channel_columns else "''"
        blocked_expr = "COALESCE(is_blocked, 0)" if "is_blocked" in channel_columns else "0"
        created_expr = "COALESCE(created_at, COALESCE(added_at, ''))" if "created_at" in channel_columns else ("COALESCE(added_at, '')" if "added_at" in channel_columns else "''")
        updated_expr = "COALESCE(updated_at, COALESCE(added_at, ''))" if "updated_at" in channel_columns else ("COALESCE(added_at, '')" if "added_at" in channel_columns else "''")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS channels_v2 (
                chat_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                avatar_url TEXT NOT NULL DEFAULT '',
                is_blocked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        cursor.execute(
            f"""
            INSERT OR REPLACE INTO channels_v2 (chat_id, title, avatar_url, is_blocked, created_at, updated_at)
            SELECT
                channel_id,
                {title_expr},
                {avatar_expr},
                {blocked_expr},
                {created_expr},
                {updated_expr}
            FROM channels
            """
        )
        cursor.execute("DROP TABLE channels")
        cursor.execute("ALTER TABLE channels_v2 RENAME TO channels")
        channel_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(channels)").fetchall()}
    if "source_post_id" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN source_post_id TEXT")
    if "source_chat_id" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN source_chat_id TEXT")
    if "button_message_id" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN button_message_id TEXT")
    if "counter_enabled" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN counter_enabled INTEGER NOT NULL DEFAULT 1")
    if "post_text" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN post_text TEXT NOT NULL DEFAULT ''")
    if "message_text" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN message_text TEXT NOT NULL DEFAULT ''")
    if "attachments_json" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'")
    if "created_at" not in post_columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
    if "avatar_url" not in user_settings_columns:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN avatar_url TEXT")
    if "consent_accepted" not in user_settings_columns:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN consent_accepted INTEGER NOT NULL DEFAULT 0")
    if "avatar_url" not in channel_columns:
        cursor.execute("ALTER TABLE channels ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''")
    if "owner_user_id" not in channel_columns:
        cursor.execute("ALTER TABLE channels ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT ''")
    if "owner_username" not in channel_columns:
        cursor.execute("ALTER TABLE channels ADD COLUMN owner_username TEXT NOT NULL DEFAULT ''")
    if "is_blocked" not in channel_columns:
        cursor.execute("ALTER TABLE channels ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0")
    if "is_deleted" not in channel_columns:
        cursor.execute("ALTER TABLE channels ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
    if "created_at" not in channel_columns:
        cursor.execute("ALTER TABLE channels ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
    if "updated_at" not in channel_columns:
        cursor.execute("ALTER TABLE channels ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_comments_post_created
        ON comments (post_id, created_at DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_posts_source_chat
        ON posts (source_chat_id, created_at DESC)
        """
    )
    conn.commit()
    conn.close()


def count_comments_in_db(db_path: str) -> int:
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT COUNT(*) FROM comments").fetchone()
        conn.close()
        return int(row[0] if row else 0)
    except sqlite3.Error:
        return 0


def count_comments_in_archive(archive_path: str) -> int:
    if not os.path.exists(archive_path):
        return 0
    temp_dir = os.path.join(DATA_DIR, f"_archive_check_{uuid.uuid4().hex}")
    try:
        os.makedirs(temp_dir, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = archive.namelist()
            if "comments.db" not in members:
                return 0
            archive.extract("comments.db", temp_dir)
            if "comments.db-wal" in members:
                archive.extract("comments.db-wal", temp_dir)
            if "comments.db-shm" in members:
                archive.extract("comments.db-shm", temp_dir)
        return count_comments_in_db(os.path.join(temp_dir, "comments.db"))
    except Exception:
        return 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def sync_store_db(reason: str = "sync") -> str | None:
    if not os.path.exists(DB_PATH):
        return None

    with BACKUP_LOCK:
        try:
            source = sqlite3.connect(DB_PATH)
            target = sqlite3.connect(STORE_DB_PATH)
            source.backup(target)
            target.close()
            source.close()
            return STORE_DB_PATH
        except sqlite3.Error as error:
            print(f"Не удалось обновить store db ({reason}): {error}")
            return None


def restore_store_db_if_needed():
    primary_count = count_comments_in_db(DB_PATH)
    mirror_count = count_comments_in_db(STORE_DB_PATH)
    should_restore = (
        (not os.path.exists(DB_PATH) and os.path.exists(STORE_DB_PATH))
        or (mirror_count > 0 and primary_count == 0)
    )
    if not should_restore:
        return False

    with BACKUP_LOCK:
        try:
            source = sqlite3.connect(STORE_DB_PATH)
            target = sqlite3.connect(DB_PATH)
            source.backup(target)
            target.close()
            source.close()
            return True
        except sqlite3.Error as error:
            print(f"Не удалось восстановить DB из {STORE_DB_PATH}: {error}")
            return False


def restore_store_archive_if_needed():
    needs_restore = (
        (not os.path.exists(DB_PATH))
        or (not os.path.isdir(UPLOAD_DIR))
        or (count_comments_in_db(DB_PATH) == 0 and os.path.exists(STORE_ARCHIVE_PATH))
    )
    if not needs_restore or not os.path.exists(STORE_ARCHIVE_PATH):
        return False

    with BACKUP_LOCK:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with zipfile.ZipFile(STORE_ARCHIVE_PATH, "r") as archive:
                members = archive.namelist()
                if "comments.db" in members:
                    archive.extract("comments.db", DATA_DIR)
                if "comments.db-wal" in members:
                    archive.extract("comments.db-wal", DATA_DIR)
                if "comments.db-shm" in members:
                    archive.extract("comments.db-shm", DATA_DIR)
                upload_members = [name for name in members if name.startswith("uploads/")]
                if upload_members:
                    os.makedirs(UPLOAD_DIR, exist_ok=True)
                    for member in upload_members:
                        archive.extract(member, DATA_DIR)
            return True
        except Exception as error:
            print(f"Не удалось восстановить данные из {STORE_ARCHIVE_PATH}: {error}")
            return False


def restore_latest_backup_if_needed():
    if count_comments_in_db(DB_PATH) > 0:
        return False
    if not os.path.isdir(BACKUP_DIR):
        return False

    backup_paths = []
    for name in os.listdir(BACKUP_DIR):
        if name.startswith("comments-backup-") and name.endswith(".zip"):
            path = os.path.join(BACKUP_DIR, name)
            if os.path.isfile(path):
                backup_paths.append(path)
    backup_paths.sort(key=lambda item: os.path.getmtime(item), reverse=True)
    if not backup_paths:
        return False

    with BACKUP_LOCK:
        for archive_path in backup_paths:
            try:
                os.makedirs(DATA_DIR, exist_ok=True)
                with zipfile.ZipFile(archive_path, "r") as archive:
                    members = archive.namelist()
                    if "comments.db" in members:
                        archive.extract("comments.db", DATA_DIR)
                    if "comments.db-wal" in members:
                        archive.extract("comments.db-wal", DATA_DIR)
                    if "comments.db-shm" in members:
                        archive.extract("comments.db-shm", DATA_DIR)
                    upload_members = [name for name in members if name.startswith("uploads/")]
                    if upload_members:
                        os.makedirs(UPLOAD_DIR, exist_ok=True)
                        for member in upload_members:
                            archive.extract(member, DATA_DIR)
                if count_comments_in_db(DB_PATH) > 0:
                    return True
            except Exception as error:
                print(f"РќРµ СѓРґР°Р»РѕСЃСЊ РІРѕСЃСЃС‚Р°РЅРѕРІРёС‚СЊ backup {archive_path}: {error}")
                continue
    return False


def prune_backups():
    entries = []
    for name in os.listdir(BACKUP_DIR):
        if not name.startswith("comments-backup-") or not name.endswith(".zip"):
            continue
        path = os.path.join(BACKUP_DIR, name)
        if os.path.isfile(path):
            entries.append((os.path.getmtime(path), path))
    entries.sort(reverse=True)
    for _, path in entries[BACKUP_RETENTION:]:
        try:
            os.remove(path)
        except OSError:
            pass


def create_backup(reason: str = "manual") -> str | None:
    if not os.path.exists(DB_PATH):
        return None

    safe_reason = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in reason.lower()).strip("-") or "manual"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = os.path.join(BACKUP_DIR, f"comments-backup-{timestamp}-{safe_reason}.zip")

    with BACKUP_LOCK:
        try:
            sync_store_db(f"{reason}-backup")
            source_db_path = STORE_DB_PATH if count_comments_in_db(STORE_DB_PATH) > 0 else DB_PATH
            manifest = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "db_path": source_db_path,
                "upload_dir": UPLOAD_DIR,
            }
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(source_db_path, arcname="comments.db")
                if os.path.isdir(UPLOAD_DIR):
                    for root, _, files in os.walk(UPLOAD_DIR):
                        for file_name in files:
                            file_path = os.path.join(root, file_name)
                            rel_path = os.path.relpath(file_path, DATA_DIR)
                            archive.write(file_path, arcname=rel_path)
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            prune_backups()
            return archive_path
        except Exception as error:
            print(f"Не удалось создать backup ({reason}): {error}")
            return None


def update_store_archive(reason: str = "sync") -> str | None:
    if not os.path.exists(DB_PATH):
        return None

    temp_archive_path = STORE_ARCHIVE_PATH + ".tmp"
    with BACKUP_LOCK:
        try:
            sync_store_db(f"{reason}-archive")
            source_db_path = STORE_DB_PATH if count_comments_in_db(STORE_DB_PATH) > 0 else DB_PATH
            manifest = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "db_path": os.path.basename(source_db_path),
                "uploads_dir": os.path.basename(UPLOAD_DIR),
                "archive_type": "comment_store",
            }
            with zipfile.ZipFile(temp_archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(source_db_path, arcname="comments.db")
                if os.path.isdir(UPLOAD_DIR):
                    for root, _, files in os.walk(UPLOAD_DIR):
                        for file_name in files:
                            file_path = os.path.join(root, file_name)
                            rel_path = os.path.relpath(file_path, DATA_DIR)
                            archive.write(file_path, arcname=rel_path)
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            os.replace(temp_archive_path, STORE_ARCHIVE_PATH)
            return STORE_ARCHIVE_PATH
        except Exception as error:
            print(f"Не удалось обновить store archive ({reason}): {error}")
            try:
                if os.path.exists(temp_archive_path):
                    os.remove(temp_archive_path)
            except OSError:
                pass
            return None


def require_sync_secret() -> bool:
    if not SYNC_SECRET:
        return False
    return request.headers.get("X-Sync-Secret", "").strip() == SYNC_SECRET


def import_store_archive(archive_path: str) -> bool:
    if not os.path.exists(archive_path):
        return False

    with BACKUP_LOCK:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with zipfile.ZipFile(archive_path, "r") as archive:
                members = archive.namelist()
                if "comments.db" in members:
                    archive.extract("comments.db", DATA_DIR)
                if "comments.db-wal" in members:
                    archive.extract("comments.db-wal", DATA_DIR)
                if "comments.db-shm" in members:
                    archive.extract("comments.db-shm", DATA_DIR)
                upload_members = [name for name in members if name.startswith("uploads/")]
                if upload_members:
                    os.makedirs(UPLOAD_DIR, exist_ok=True)
                    for member in upload_members:
                        archive.extract(member, DATA_DIR)
            sync_store_db("sync-import")
            update_store_archive("sync-import")
            create_backup("sync-import")
            return True
        except Exception as error:
            print(f"Не удалось импортировать store archive {archive_path}: {error}")
            return False


def normalize_post_id(raw_post_id: str | None) -> str:
    return (raw_post_id or "").strip()[:128]


def encode_post_payload(raw_post_id: str | None) -> str:
    normalized = normalize_post_id(raw_post_id)
    if not normalized:
        return ""
    return base64.urlsafe_b64encode(normalized.encode("utf-8")).decode("ascii").rstrip("=")[:128]


def decode_post_payload(raw_post_id: str | None) -> str:
    normalized = normalize_post_id(raw_post_id)
    if not normalized or normalized.startswith("mid."):
        return normalized if normalized.startswith("mid.") else ""
    try:
        padding = "=" * (-len(normalized) % 4)
        decoded = base64.urlsafe_b64decode((normalized + padding).encode("ascii")).decode("utf-8")
    except Exception:
        return ""
    return normalize_post_id(decoded)


def get_post_id_candidates(raw_post_id: str | None) -> list[str]:
    normalized = normalize_post_id(raw_post_id)
    if not normalized:
        return []
    candidates: list[str] = []

    def add(candidate: str | None):
        candidate = normalize_post_id(candidate)
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    add(normalized)
    decoded = decode_post_payload(normalized)
    add(decoded)
    if normalized.startswith("mid."):
        add(encode_post_payload(normalized))
    if decoded.startswith("mid."):
        add(encode_post_payload(decoded))
    return candidates


def get_preferred_post_storage_id(raw_post_id: str | None) -> str:
    normalized = normalize_post_id(raw_post_id)
    if not normalized:
        return ""
    if normalized.startswith("mid."):
        encoded = encode_post_payload(normalized)
        return encoded or normalized
    decoded = decode_post_payload(normalized)
    if decoded.startswith("mid."):
        return normalized
    return normalized


def normalize_comment(raw_comment: str | None) -> str:
    return (raw_comment or "").strip()[:1000]


def build_file_url(file_path: str | None) -> str | None:
    if not file_path:
        return None
    return f"/uploads/{file_path}"


def allowed_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


def sniff_media_type(file_storage) -> tuple[str | None, str | None]:
    stream = file_storage.stream
    position = stream.tell()
    header = stream.read(64)
    stream.seek(position)

    if header.startswith(b"\xff\xd8\xff"):
        return "image", ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", ".png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image", ".gif"
    if header.startswith(b"BM"):
        return "image", ".bmp"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image", ".webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        major_brand = header[8:12]
        if major_brand == b"qt  ":
            return "video", ".mov"
        if major_brand in {b"M4V ", b"M4VH", b"M4VP"}:
            return "video", ".m4v"
        return "video", ".mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", ".webm"
    return None, None


def get_stream_size(file_storage) -> int:
    stream = file_storage.stream
    position = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(position)
    return size


def validate_media_file(file_storage) -> tuple[str, str]:
    if not file_storage or not file_storage.filename:
        raise ValueError("Файл не выбран")

    detected_type, detected_ext = sniff_media_type(file_storage)
    if not detected_type or not detected_ext:
        raise ValueError("Разрешены только безопасные фото и видео форматов JPG, PNG, GIF, WEBP, BMP, MP4, MOV, WEBM, M4V")

    size = get_stream_size(file_storage)
    if detected_type == "image" and size > MAX_IMAGE_BYTES:
        raise ValueError("Фото слишком большое. Максимум 15 МБ")
    if detected_type == "video" and size > MAX_VIDEO_BYTES:
        raise ValueError("Видео слишком большое. Максимум 80 МБ")

    mime_type = (file_storage.mimetype or "").lower().strip()
    if detected_type == "image" and mime_type and not mime_type.startswith("image/"):
        raise ValueError("Файл не похож на изображение")
    if detected_type == "video" and mime_type and not mime_type.startswith("video/"):
        raise ValueError("Файл не похож на видео")

    original_name = secure_filename(file_storage.filename) or "upload"
    original_ext = os.path.splitext(original_name.lower())[1]
    if original_ext and original_ext in ALLOWED_EXTENSIONS:
        if detected_type == "image" and original_ext not in IMAGE_EXTENSIONS:
            raise ValueError("Разрешены только изображения")
        if detected_type == "video" and original_ext not in VIDEO_EXTENSIONS:
            raise ValueError("Разрешены только видео")

    return detected_type, detected_ext


def save_uploaded_media(file_storage):
    if not file_storage or not file_storage.filename:
        return None, None
    media_type, ext = validate_media_file(file_storage)
    stored_name = f"{uuid.uuid4().hex}{ext.lower()}"
    file_storage.save(os.path.join(UPLOAD_DIR, stored_name))
    return stored_name, media_type


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

    first_name = (user.get("first_name") or user.get("firstName") or "").strip()
    last_name = (user.get("last_name") or user.get("lastName") or "").strip()
    username = " ".join(part for part in [first_name, last_name] if part).strip()
    if not username:
        username = (user.get("username") or "Пользователь MAX").strip()

    user_id = str(user.get("user_id") or user.get("id") or "").strip()
    if not user_id:
        return None
    public_username = (user.get("username") or user.get("login") or "").strip()
    avatar = user.get("avatar") if isinstance(user.get("avatar"), dict) else {}
    photo = user.get("photo") if isinstance(user.get("photo"), dict) else {}
    avatar_url = (
        user.get("avatar_url")
        or user.get("avatarUrl")
        or user.get("full_avatar_url")
        or user.get("fullAvatarUrl")
        or user.get("photo_url")
        or user.get("photoUrl")
        or user.get("picture")
        or avatar.get("url")
        or avatar.get("full_url")
        or photo.get("url")
        or photo.get("full_url")
        or ""
    ).strip()
    return {
        "user_id": user_id[:128],
        "username": username[:50] or "Пользователь MAX",
        "public_username": public_username[:128],
        "avatar_url": avatar_url[:1000],
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


def serialize_comment(row: sqlite3.Row, comment_lookup: dict | None = None) -> dict:
    parent_preview = None
    if comment_lookup and row["parent_id"] and row["parent_id"] in comment_lookup:
        parent = comment_lookup[row["parent_id"]]
        parent_preview = {
            "username": parent["username"],
            "comment": (parent["comment"] or "Фото")[:80],
        }

    media_path = row["media_path"] if "media_path" in row.keys() else row["image_path"]
    media_type = row["media_type"] if "media_type" in row.keys() and row["media_type"] else ("image" if media_path else None)
    return {
        "id": row["id"],
        "post_id": row["post_id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "author_type": row["author_type"] if "author_type" in row.keys() else "user",
        "channel_chat_id": row["channel_chat_id"] if "channel_chat_id" in row.keys() else "",
        "public_username": row["public_username"] if "public_username" in row.keys() else "",
        "avatar_url": row["avatar_url"] if "avatar_url" in row.keys() else "",
        "comment": row["comment"],
        "image_url": build_file_url(media_path),
        "media_type": media_type,
        "parent_id": row["parent_id"],
        "parent_preview": parent_preview,
        "edited_at": row["edited_at"],
        "created_at": row["created_at"],
        "can_edit": False,
        "can_delete": False,
    }


def get_post_info(post_id: str) -> dict | None:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT post_id, source_post_id, source_chat_id, button_message_id, counter_enabled, post_text, message_text, attachments_json, created_at FROM posts WHERE post_id = ?",
        (post_id,),
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT post_id, source_post_id, source_chat_id, button_message_id, counter_enabled, post_text, message_text, attachments_json, created_at FROM posts WHERE source_post_id = ?",
            (post_id,),
        ).fetchone()
    conn.close()
    if not row:
        return None
    channel = get_channel_info(row["source_chat_id"]) if row["source_chat_id"] else None
    return {
        "post_id": row["post_id"],
        "source_post_id": row["source_post_id"],
        "source_chat_id": row["source_chat_id"],
        "button_message_id": row["button_message_id"],
        "counter_enabled": row["counter_enabled"],
        "post_text": row["post_text"],
        "message_text": row["message_text"],
        "attachments_json": row["attachments_json"],
        "created_at": row["created_at"],
        "channel_title": (channel or {}).get("title", ""),
        "channel_avatar_url": (channel or {}).get("avatar_url", ""),
        "channel_is_blocked": bool((channel or {}).get("is_blocked", False)),
    }


def build_placeholder_post_info(post_id: str, source_post_id: str | None = None) -> dict:
    normalized_post_id = normalize_post_id(post_id)
    normalized_source_post_id = normalize_post_id(source_post_id)
    if not normalized_source_post_id:
        decoded = decode_post_payload(normalized_post_id)
        normalized_source_post_id = decoded if decoded.startswith("mid.") else ""
    return {
        "post_id": normalized_post_id,
        "source_post_id": normalized_source_post_id,
        "source_chat_id": "",
        "button_message_id": "",
        "counter_enabled": 0,
        "post_text": "",
        "message_text": "",
        "attachments_json": "[]",
        "created_at": "",
        "channel_title": "",
        "channel_avatar_url": "",
        "channel_is_blocked": False,
    }


def resolve_post_id(post_id: str) -> str:
    candidates = get_post_id_candidates(post_id)
    if not candidates:
        return ""
    for candidate in candidates:
        post = get_post_info(candidate)
        if post and post.get("post_id"):
            return str(post["post_id"])

    preferred = get_preferred_post_storage_id(post_id)
    conn = get_db_connection()
    for candidate in [preferred] + [item for item in candidates if item != preferred]:
        row = conn.execute("SELECT COUNT(*) AS count FROM comments WHERE post_id = ?", (candidate,)).fetchone()
        if row and int(row["count"] or 0) > 0:
            conn.close()
            return candidate
    conn.close()
    return preferred


def ensure_post_record(post_id: str, source_post_id: str | None = None) -> dict | None:
    normalized_post_id = resolve_post_id(post_id)
    if not normalized_post_id:
        return None
    post = get_post_info(normalized_post_id)
    if post:
        return post

    placeholder = build_placeholder_post_info(normalized_post_id, source_post_id=source_post_id or post_id)
    conn = get_db_connection()
    conn.execute(
        """
        INSERT OR IGNORE INTO posts (post_id, source_post_id, source_chat_id, button_message_id, counter_enabled, post_text, message_text, attachments_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            placeholder["post_id"],
            placeholder["source_post_id"],
            placeholder["source_chat_id"],
            placeholder["button_message_id"],
            placeholder["counter_enabled"],
            placeholder["post_text"],
            placeholder["message_text"],
            placeholder["attachments_json"],
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return get_post_info(normalized_post_id) or placeholder


def get_channel_info(chat_id: str) -> dict | None:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        return None

    conn = get_db_connection()
    row = conn.execute(
        "SELECT chat_id, title, avatar_url, owner_user_id, owner_username, is_blocked, is_deleted, created_at, updated_at FROM channels WHERE chat_id = ?",
        (normalized_chat_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "chat_id": row["chat_id"],
        "title": row["title"] or "",
        "avatar_url": row["avatar_url"] or "",
        "owner_user_id": row["owner_user_id"] or "",
        "owner_username": row["owner_username"] or "",
        "is_blocked": bool(row["is_blocked"]),
        "is_deleted": bool(row["is_deleted"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert_channel(
    chat_id: str,
    title: str = "",
    avatar_url: str = "",
    owner_user_id: str = "",
    owner_username: str = "",
    is_blocked: int | None = None,
    is_deleted: int | None = None,
):
    normalized_chat_id = str(chat_id or "").strip()[:256]
    if not normalized_chat_id:
        return
    existing = get_channel_info(normalized_chat_id)
    now = datetime.now(timezone.utc).isoformat()
    final_blocked = int(existing["is_blocked"]) if existing and is_blocked is None else int(1 if is_blocked else 0)
    final_deleted = int(existing["is_deleted"]) if existing and is_deleted is None else int(1 if is_deleted else 0)
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO channels (chat_id, title, avatar_url, owner_user_id, owner_username, is_blocked, is_deleted, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE channels.title END,
            avatar_url = CASE WHEN excluded.avatar_url <> '' THEN excluded.avatar_url ELSE channels.avatar_url END,
            owner_user_id = CASE WHEN channels.owner_user_id = '' AND excluded.owner_user_id <> '' THEN excluded.owner_user_id ELSE channels.owner_user_id END,
            owner_username = CASE
                WHEN channels.owner_user_id = '' AND excluded.owner_username <> '' THEN excluded.owner_username
                WHEN channels.owner_user_id = excluded.owner_user_id AND excluded.owner_username <> '' THEN excluded.owner_username
                ELSE channels.owner_username
            END,
            is_blocked = excluded.is_blocked,
            is_deleted = excluded.is_deleted,
            updated_at = excluded.updated_at
        """,
        (
            normalized_chat_id,
            (title or "").strip()[:255],
            (avatar_url or "").strip()[:1000],
            str(owner_user_id or "").strip()[:128],
            (owner_username or "").strip()[:255],
            final_blocked,
            final_deleted,
            existing["created_at"] if existing else now,
            now,
        ),
    )
    conn.commit()
    conn.close()


def _channel_needs_refresh(title: str, chat_id: str, avatar_url: str = "") -> bool:
    normalized_title = str(title or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_avatar = str(avatar_url or "").strip()
    return not normalized_title or normalized_title == normalized_chat_id or not normalized_avatar


def hydrate_channel_info(channel: dict) -> dict:
    if not channel:
        return channel
    chat_id = str(channel.get("chat_id") or "").strip()
    if not chat_id:
        return channel
    title = str(channel.get("title") or "").strip()
    avatar_url = str(channel.get("avatar_url") or "").strip()
    if not _channel_needs_refresh(title, chat_id, avatar_url):
        return channel
    chat_info = fetch_chat_info(chat_id) or {}
    refreshed_title = (chat_info.get("title") or title or chat_id).strip()
    refreshed_avatar_url = (chat_info.get("avatar_url") or avatar_url or "").strip()
    if refreshed_title != title or refreshed_avatar_url != avatar_url:
        upsert_channel(chat_id, title=refreshed_title, avatar_url=refreshed_avatar_url, is_blocked=1 if channel.get("is_blocked") else 0)
    updated_channel = dict(channel)
    updated_channel["title"] = refreshed_title
    updated_channel["avatar_url"] = refreshed_avatar_url
    return updated_channel


def list_channels(owner_user_id: str | None = None, include_deleted: bool = False) -> list[dict]:
    normalized_owner_user_id = str(owner_user_id or "").strip()
    conn = get_db_connection()
    where_parts = []
    params: list[str] = []
    if normalized_owner_user_id:
        where_parts.append("channels.owner_user_id = ?")
        params.append(normalized_owner_user_id)
    if not include_deleted:
        where_parts.append("COALESCE(channels.is_deleted, 0) = 0")
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    rows = conn.execute(
        f"""
        SELECT channels.chat_id, channels.title, channels.avatar_url, channels.owner_user_id, channels.owner_username, channels.is_blocked, channels.is_deleted, channels.created_at, channels.updated_at,
               COUNT(posts.post_id) AS posts_count
        FROM channels
        LEFT JOIN posts ON posts.source_chat_id = channels.chat_id
        {where_sql}
        GROUP BY channels.chat_id, channels.title, channels.avatar_url, channels.owner_user_id, channels.owner_username, channels.is_blocked, channels.is_deleted, channels.created_at, channels.updated_at
        ORDER BY channels.updated_at DESC, channels.chat_id DESC
        """,
        params,
    ).fetchall()
    conn.close()
    channels = [
        {
            "chat_id": row["chat_id"],
            "title": row["title"] or row["chat_id"],
            "avatar_url": row["avatar_url"] or "",
            "owner_user_id": row["owner_user_id"] or "",
            "owner_username": row["owner_username"] or "",
            "is_blocked": bool(row["is_blocked"]),
            "is_deleted": bool(row["is_deleted"]),
            "posts_count": int(row["posts_count"] or 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    return [hydrate_channel_info(channel) for channel in channels]


def normalize_stats_period(raw_period: str | None) -> str:
    value = str(raw_period or "").strip().lower()
    if value in {"month", "месяц", "monthly", "30d", "30"}:
        return "month"
    return "week"


def _safe_post_label(post_row: sqlite3.Row | dict) -> str:
    post_text = str((post_row.get("post_text") if isinstance(post_row, dict) else post_row["post_text"]) or "").strip()
    message_text = str((post_row.get("message_text") if isinstance(post_row, dict) else post_row["message_text"]) or "").strip()
    source_post_id = str((post_row.get("source_post_id") if isinstance(post_row, dict) else post_row["source_post_id"]) or "").strip()
    label = post_text or message_text or source_post_id or "Пост без текста"
    return " ".join(label.split())[:80]


def get_channel_stats(chat_id: str | None = None, period: str = "week", owner_user_id: str | None = None) -> dict:
    normalized_chat_id = str(chat_id or "").strip()
    normalized_owner_user_id = str(owner_user_id or "").strip()
    normalized_period = normalize_stats_period(period)
    days = 30 if normalized_period == "month" else 7
    now = datetime.now(timezone.utc)
    since_dt = now - timedelta(days=days)
    since_iso = since_dt.isoformat()
    conn = get_db_connection()

    channel_join = "JOIN channels ON channels.chat_id = posts.source_chat_id"
    owner_filter = " AND channels.owner_user_id = ?" if normalized_owner_user_id else ""
    deleted_filter = " AND COALESCE(channels.is_deleted, 0) = 0"

    if normalized_chat_id:
        channel_filter = " AND posts.source_chat_id = ?"
        channel_params = [normalized_chat_id]
        channel = hydrate_channel_info(get_channel_info(normalized_chat_id) or {
            "chat_id": normalized_chat_id,
            "title": normalized_chat_id,
            "avatar_url": "",
            "owner_user_id": "",
            "owner_username": "",
            "is_blocked": False,
            "is_deleted": False,
        })
        if normalized_owner_user_id and str(channel.get("owner_user_id") or "").strip() not in {"", normalized_owner_user_id}:
            channel = {
                "chat_id": normalized_chat_id,
                "title": normalized_chat_id,
                "avatar_url": "",
                "owner_user_id": normalized_owner_user_id,
                "owner_username": "",
                "is_blocked": False,
                "is_deleted": False,
            }
            channel_filter = " AND 1 = 0"
            channel_params = []
    else:
        channel_filter = ""
        channel_params = []
        channel = None

    posts_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS posts_count,
            SUM(CASE WHEN counter_enabled = 1 THEN 1 ELSE 0 END) AS counter_enabled_posts_count
        FROM posts
        {channel_join}
        WHERE posts.created_at >= ? {channel_filter}{owner_filter}{deleted_filter}
        """,
        [since_iso, *channel_params, *(([normalized_owner_user_id] if normalized_owner_user_id else []))],
    ).fetchone()

    comments_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS comments_count,
            COUNT(DISTINCT comments.user_id) AS unique_commenters,
            SUM(CASE WHEN comments.parent_id IS NOT NULL THEN 1 ELSE 0 END) AS replies_count,
            SUM(CASE WHEN TRIM(COALESCE(comments.media_path, '')) <> '' THEN 1 ELSE 0 END) AS media_comments_count,
            SUM(CASE WHEN comments.author_type = 'channel' THEN 1 ELSE 0 END) AS channel_comments_count
        FROM comments
        JOIN posts ON posts.post_id = comments.post_id
        {channel_join}
        WHERE comments.created_at >= ? {channel_filter}{owner_filter}{deleted_filter}
        """,
        [since_iso, *channel_params, *(([normalized_owner_user_id] if normalized_owner_user_id else []))],
    ).fetchone()

    lifetime_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS comments_total,
            COUNT(DISTINCT comments.user_id) AS commenters_total
        FROM comments
        JOIN posts ON posts.post_id = comments.post_id
        {channel_join}
        WHERE 1 = 1 {channel_filter}{owner_filter}{deleted_filter}
        """,
        [*channel_params, *(([normalized_owner_user_id] if normalized_owner_user_id else []))],
    ).fetchone()

    active_channels_row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT source_chat_id) AS active_channels
        FROM posts
        {channel_join}
        WHERE posts.created_at >= ? AND TRIM(COALESCE(source_chat_id, '')) <> ''{owner_filter}{deleted_filter}
        """,
        [since_iso, *(([normalized_owner_user_id] if normalized_owner_user_id else []))],
    ).fetchone()

    top_posts_rows = conn.execute(
        f"""
        SELECT
            posts.post_id,
            posts.source_post_id,
            posts.post_text,
            posts.message_text,
            COUNT(comments.id) AS comments_count,
            MAX(comments.created_at) AS last_comment_at
        FROM posts
        {channel_join}
        LEFT JOIN comments
            ON comments.post_id = posts.post_id
           AND comments.created_at >= ?
        WHERE 1 = 1 {channel_filter}{owner_filter}{deleted_filter}
        GROUP BY posts.post_id, posts.source_post_id, posts.post_text, posts.message_text
        HAVING comments_count > 0
        ORDER BY comments_count DESC, last_comment_at DESC
        LIMIT 5
        """,
        [since_iso, *channel_params, *(([normalized_owner_user_id] if normalized_owner_user_id else []))],
    ).fetchall()

    top_commenters_rows = conn.execute(
        f"""
        SELECT
            comments.user_id,
            comments.username,
            comments.author_type,
            COUNT(*) AS comments_count,
            MAX(comments.created_at) AS last_comment_at
        FROM comments
        JOIN posts ON posts.post_id = comments.post_id
        {channel_join}
        WHERE comments.created_at >= ? {channel_filter}{owner_filter}{deleted_filter}
        GROUP BY comments.user_id, comments.username, comments.author_type
        ORDER BY comments_count DESC, last_comment_at DESC
        LIMIT 5
        """,
        [since_iso, *channel_params, *(([normalized_owner_user_id] if normalized_owner_user_id else []))],
    ).fetchall()

    activity_rows = conn.execute(
        f"""
        SELECT
            SUBSTR(comments.created_at, 1, 10) AS day,
            COUNT(*) AS comments_count
        FROM comments
        JOIN posts ON posts.post_id = comments.post_id
        {channel_join}
        WHERE comments.created_at >= ? {channel_filter}{owner_filter}{deleted_filter}
        GROUP BY SUBSTR(comments.created_at, 1, 10)
        ORDER BY day ASC
        """,
        [since_iso, *channel_params, *(([normalized_owner_user_id] if normalized_owner_user_id else []))],
    ).fetchall()
    conn.close()

    posts_count = int((posts_row["posts_count"] or 0) if posts_row else 0)
    comments_count = int((comments_row["comments_count"] or 0) if comments_row else 0)
    unique_commenters = int((comments_row["unique_commenters"] or 0) if comments_row else 0)
    replies_count = int((comments_row["replies_count"] or 0) if comments_row else 0)
    media_comments_count = int((comments_row["media_comments_count"] or 0) if comments_row else 0)
    channel_comments_count = int((comments_row["channel_comments_count"] or 0) if comments_row else 0)
    counter_enabled_posts_count = int((posts_row["counter_enabled_posts_count"] or 0) if posts_row else 0)
    comments_total = int((lifetime_row["comments_total"] or 0) if lifetime_row else 0)
    commenters_total = int((lifetime_row["commenters_total"] or 0) if lifetime_row else 0)
    active_channels = int((active_channels_row["active_channels"] or 0) if active_channels_row else 0)

    activity_map = {str(row["day"]): int(row["comments_count"] or 0) for row in activity_rows}
    activity_by_day = []
    for offset in range(days):
        day = (since_dt + timedelta(days=offset)).date().isoformat()
        activity_by_day.append({"day": day, "comments_count": activity_map.get(day, 0)})

    top_posts = [
        {
            "post_id": row["post_id"],
            "source_post_id": row["source_post_id"],
            "label": _safe_post_label(row),
            "comments_count": int(row["comments_count"] or 0),
            "last_comment_at": row["last_comment_at"] or "",
        }
        for row in top_posts_rows
    ]
    top_commenters = [
        {
            "user_id": row["user_id"],
            "username": row["username"] or "Пользователь",
            "author_type": row["author_type"] or "user",
            "comments_count": int(row["comments_count"] or 0),
            "last_comment_at": row["last_comment_at"] or "",
        }
        for row in top_commenters_rows
    ]

    avg_comments_per_post = round(comments_count / posts_count, 2) if posts_count else 0.0
    active_days = sum(1 for item in activity_by_day if item["comments_count"] > 0)

    return {
        "period": normalized_period,
        "days": days,
        "scope": "channel" if normalized_chat_id else "all",
        "generated_at": now.isoformat(),
        "since": since_dt.isoformat(),
        "channel": channel,
        "summary": {
            "posts_count": posts_count,
            "counter_enabled_posts_count": counter_enabled_posts_count,
            "comments_count": comments_count,
            "comments_total": comments_total,
            "unique_commenters": unique_commenters,
            "commenters_total": commenters_total,
            "replies_count": replies_count,
            "media_comments_count": media_comments_count,
            "channel_comments_count": channel_comments_count,
            "avg_comments_per_post": avg_comments_per_post,
            "active_days": active_days,
            "active_channels": active_channels,
        },
        "top_posts": top_posts,
        "top_commenters": top_commenters,
        "activity_by_day": activity_by_day,
    }


def set_channel_block(chat_id: str, is_blocked: bool):
    channel = get_channel_info(chat_id)
    if not channel:
        upsert_channel(chat_id, title="", avatar_url="", is_blocked=1 if is_blocked else 0)
    else:
        upsert_channel(
            chat_id,
            title=channel["title"],
            avatar_url=channel["avatar_url"],
            owner_user_id=channel.get("owner_user_id", ""),
            owner_username=channel.get("owner_username", ""),
            is_blocked=1 if is_blocked else 0,
            is_deleted=1 if channel.get("is_deleted") else 0,
        )


def set_channel_deleted(chat_id: str, is_deleted: bool):
    channel = get_channel_info(chat_id)
    if not channel:
        upsert_channel(chat_id, title="", avatar_url="", is_blocked=1 if is_deleted else 0, is_deleted=1 if is_deleted else 0)
    else:
        upsert_channel(
            chat_id,
            title=channel["title"],
            avatar_url=channel["avatar_url"],
            owner_user_id=channel.get("owner_user_id", ""),
            owner_username=channel.get("owner_username", ""),
            is_blocked=1 if is_deleted else int(1 if channel.get("is_blocked") else 0),
            is_deleted=1 if is_deleted else 0,
        )


def upsert_user_settings(user: dict, notifications_enabled: int | None = None, consent_accepted: int | None = None):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    existing = conn.execute(
        "SELECT notifications_enabled, consent_accepted FROM user_settings WHERE user_id = ?",
        (user["user_id"],),
    ).fetchone()
    effective_notifications = existing["notifications_enabled"] if existing and notifications_enabled is None else int(1 if notifications_enabled is None else notifications_enabled)
    effective_consent = existing["consent_accepted"] if existing and consent_accepted is None else int(1 if consent_accepted else 0)
    conn.execute(
        """
        INSERT INTO user_settings (user_id, username, public_username, avatar_url, notifications_enabled, consent_accepted, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            public_username = excluded.public_username,
            avatar_url = excluded.avatar_url,
            notifications_enabled = excluded.notifications_enabled,
            consent_accepted = excluded.consent_accepted,
            updated_at = excluded.updated_at
        """,
        (
            user["user_id"],
            user["username"],
            user.get("public_username", ""),
            user.get("avatar_url", ""),
            effective_notifications,
            effective_consent,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()


def get_user_settings(user_id: str) -> dict:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT user_id, username, public_username, avatar_url, notifications_enabled, consent_accepted FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {"notifications_enabled": True}
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "public_username": row["public_username"] or "",
        "avatar_url": row["avatar_url"] or "",
        "notifications_enabled": bool(row["notifications_enabled"]),
        "consent_accepted": bool(row["consent_accepted"]),
    }


def build_profile_url(public_username: str | None) -> str | None:
    username = (public_username or "").strip()
    if not username:
        return None
    return f"https://max.ru/{username}"


def _extract_member_user_id(payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    nested_candidates = [
        payload,
        payload.get("user") if isinstance(payload.get("user"), dict) else None,
        payload.get("member") if isinstance(payload.get("member"), dict) else None,
        payload.get("participant") if isinstance(payload.get("participant"), dict) else None,
        payload.get("profile") if isinstance(payload.get("profile"), dict) else None,
    ]
    for candidate in nested_candidates:
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("user_id") or candidate.get("id")
        if value is not None and str(value).strip():
            return str(value)
    return None


def _member_is_admin(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    nested_candidates = [
        payload,
        payload.get("user") if isinstance(payload.get("user"), dict) else None,
        payload.get("member") if isinstance(payload.get("member"), dict) else None,
        payload.get("participant") if isinstance(payload.get("participant"), dict) else None,
        payload.get("permissions") if isinstance(payload.get("permissions"), dict) else None,
    ]
    for candidate in nested_candidates:
        if not isinstance(candidate, dict):
            continue
        role_values = [
            candidate.get("role"),
            candidate.get("member_role"),
            candidate.get("status"),
            candidate.get("type"),
        ]
        role_text = " ".join(str(value).lower() for value in role_values if value)
        if any(flag in role_text for flag in ("admin", "owner", "creator", "moderator")):
            return True
        for key in (
            "is_admin",
            "is_owner",
            "admin",
            "owner",
            "creator",
            "can_delete_messages",
            "can_delete_all_messages",
            "can_moderate",
            "can_manage",
        ):
            if candidate.get(key):
                return True
    return False


def get_chat_admin_ids(chat_id: str) -> set[str]:
    if not BOT_TOKEN or not chat_id:
        return set()

    urls = [
        f"https://platform-api.max.ru/chats/{chat_id}/members/admins",
        f"https://platform-api.max.ru/chats/{chat_id}",
    ]
    for url in urls:
        try:
            req = Request(
                url=url,
                headers={"Authorization": BOT_TOKEN},
                method="GET",
            )
            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            admins: set[str] = set()
            if isinstance(data, list):
                for item in data:
                    candidate = _extract_member_user_id(item)
                    if candidate is not None:
                        admins.add(candidate)
            elif isinstance(data, dict):
                direct_candidate = _extract_member_user_id(data)
                if direct_candidate and _member_is_admin(data):
                    admins.add(direct_candidate)
                members = (
                    data.get("members")
                    or data.get("participants")
                    or data.get("admins")
                    or data.get("items")
                    or []
                )
                for item in members:
                    candidate = _extract_member_user_id(item)
                    if candidate is not None and _member_is_admin(item):
                        admins.add(candidate)
            if admins:
                return admins
        except Exception:
            continue
    return set()


def is_chat_admin(chat_id: str, user_id: str) -> bool:
    if not BOT_TOKEN or not chat_id or not user_id:
        return False

    urls = [
        f"https://platform-api.max.ru/chats/{chat_id}/members?user_ids={quote(str(user_id))}",
        f"https://platform-api.max.ru/chats/{chat_id}/members/{quote(str(user_id))}",
    ]
    for url in urls:
        try:
            req = Request(
                url=url,
                headers={"Authorization": BOT_TOKEN},
                method="GET",
            )
            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, list):
                for item in data:
                    if _extract_member_user_id(item) == str(user_id) and _member_is_admin(item):
                        return True
            elif isinstance(data, dict):
                direct_candidate = _extract_member_user_id(data)
                if direct_candidate == str(user_id) and _member_is_admin(data):
                    return True
                members = data.get("members") or data.get("participants") or data.get("items") or []
                for item in members:
                    if _extract_member_user_id(item) == str(user_id) and _member_is_admin(item):
                        return True
        except Exception:
            continue
    return str(user_id) in get_chat_admin_ids(chat_id)


def fetch_chat_info(chat_id: str) -> dict | None:
    normalized_chat_id = str(chat_id or "").strip()
    if not BOT_TOKEN or not normalized_chat_id:
        return None
    try:
        req = Request(
            url=f"https://platform-api.max.ru/chats/{quote(normalized_chat_id, safe='')}",
            headers={"Authorization": BOT_TOKEN},
            method="GET",
        )
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict):
            return None
        return {
            "chat_id": normalized_chat_id,
            "title": (data.get("title") or data.get("name") or data.get("display_name") or "").strip()[:255],
            "avatar_url": (data.get("avatar_url") or data.get("full_avatar_url") or "").strip()[:1000],
        }
    except Exception:
        return None


def user_can_moderate_comment(user_id: str, post_id: str) -> bool:
    post = get_post_info(post_id)
    if not post:
        return False
    source_chat_id = str(post.get("source_chat_id") or "").strip()
    if not source_chat_id:
        return False
    return is_chat_admin(source_chat_id, str(user_id))


def _build_comment_preview(actor_comment: str) -> str:
    return (actor_comment or "").strip() or "Фото/видео"


def send_bot_private_message(target_user_id: str, payload: dict):
    if not BOT_TOKEN or not target_user_id:
        return
    try:
        req = Request(
            url=f"https://botapi.max.ru/messages?user_id={quote(str(target_user_id), safe='')}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": BOT_TOKEN,
            },
            method="POST",
        )
        with urlopen(req, timeout=10) as response:
            response.read()
    except Exception as error:
        print(f"Не удалось отправить личное сообщение пользователю {str(target_user_id)[:32]}: {error}")


def send_reply_notification(target_user_id: str, actor_name: str, actor_comment: str, post_id: str):
    if not BOT_TOKEN or not target_user_id:
        return
    preview = _build_comment_preview(actor_comment)
    text = f"Вам ответили в комментариях.\n\n{actor_name}: {preview[:300]}"
    payload = {
        "text": text,
        "notify": True,
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [[
                        {
                            "type": "link",
                            "text": "Открыть комментарии",
                            "url": f"https://max.ru/{BOT_USERNAME}?startapp={post_id}",
                        }
                    ]]
                }
            }
        ],
    }

    send_bot_private_message(target_user_id, payload)


def send_channel_admin_notifications(post_id: str, actor_user_id: str, actor_name: str, actor_comment: str):
    post = get_post_info(post_id)
    source_chat_id = str((post or {}).get("source_chat_id") or "").strip()
    if not source_chat_id or not BOT_TOKEN:
        return

    channel = get_channel_info(source_chat_id) or {}
    channel_title = channel.get("title") or source_chat_id
    preview = _build_comment_preview(actor_comment)
    post_preview = ((post or {}).get("post_text") or (post or {}).get("message_text") or "").strip()
    text = f"Новый комментарий в канале «{channel_title}».\n\n{actor_name}: {preview[:300]}"
    if post_preview:
        text = f"{text}\n\nПост: {post_preview[:200]}"
    payload = {
        "text": text,
        "notify": True,
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [[
                        {
                            "type": "link",
                            "text": "Открыть комментарии",
                            "url": f"https://max.ru/{BOT_USERNAME}?startapp={post_id}",
                        }
                    ]]
                }
            }
        ],
    }

    for admin_id in get_chat_admin_ids(source_chat_id):
        if str(admin_id) == str(actor_user_id):
            continue
        target_settings = get_user_settings(admin_id)
        if not target_settings.get("notifications_enabled", True):
            continue
        send_bot_private_message(admin_id, payload)


def refresh_post_button(post_id: str):
    post = get_post_info(post_id)
    target_message_id = (post or {}).get("button_message_id") or (post or {}).get("source_post_id")
    if not post or not target_message_id or not post.get("counter_enabled"):
        return

    conn = get_db_connection()
    count_row = conn.execute("SELECT COUNT(*) AS count FROM comments WHERE post_id = ?", (post_id,)).fetchone()
    conn.close()
    count = count_row["count"] if count_row else 0
    button_text = f"Комментарии ({count})" if count else "Открыть комментарии"

    try:
        attachments = json.loads(post.get("attachments_json") or "[]")
        if not isinstance(attachments, list):
            attachments = []
    except json.JSONDecodeError:
        attachments = []
    attachments = [attachment for attachment in attachments if isinstance(attachment, dict) and attachment.get("type") != "inline_keyboard"]

    attachments.append(
        {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [[
                    {
                        "type": "link",
                        "text": button_text,
                        "url": f"https://max.ru/{BOT_USERNAME}?startapp={post_id}",
                    }
                ]]
            }
        }
    )

    payload = {
        "text": post.get("message_text", ""),
        "notify": True,
        "attachments": attachments,
    }

    # ИСПРАВЛЕНО: убран access_token из URL, message_id перенесён в путь, добавлен заголовок Authorization
    try:
        req = Request(
            url=f"https://platform-api.max.ru/messages?message_id={quote(str(target_message_id), safe='')}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": BOT_TOKEN
            },
            method="PUT",
        )
        with urlopen(req, timeout=10) as response:
            response.read()
    except Exception as error:
        if isinstance(error, HTTPError):
            try:
                details = error.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                details = str(error)
            print(f"Не удалось обновить кнопку комментариев для {post_id[:32]}: HTTP {error.code} {details}")
        else:
            print(f"Не удалось обновить кнопку комментариев для {post_id[:32]}: {error}")


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
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
            --composer-space: 120px;
        }

        * {
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
            -webkit-user-select: none;
            user-select: none;
        }

        html, body {
            margin: 0;
            min-height: 100%;
            background: var(--tg-bg);
            color: var(--tg-text);
            font-family: "Segoe UI", Tahoma, sans-serif;
            overflow-x: hidden;
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
            justify-content: center;
            font-size: 17px;
            font-weight: 700;
        }

        .topbar-inner {
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .notify-toggle {
            position: absolute;
            right: 0;
            top: 50%;
            transform: translateY(-50%);
            width: 38px;
            height: 38px;
            border: none;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.08);
            color: #d7e7f6;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
        }

        .notify-toggle.active {
            color: #8fd3ff;
            background: rgba(46, 166, 255, 0.16);
        }

        .title-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #52d273;
            box-shadow: 0 0 10px rgba(82, 210, 115, 0.6);
        }

        .post-card {
            margin: 10px 12px 8px;
            padding: 10px 12px;
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
            padding: 2px 12px calc(var(--composer-space) + 12px);
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .message-thread {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .message-thread.reply {
            margin-left: 28px;
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
            overflow: hidden;
            cursor: pointer;
            background-size: cover;
            background-position: center;
        }

        .avatar img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }

        .bubble {
            max-width: min(85%, 560px);
            padding: 8px 12px 7px;
            border-radius: 18px 18px 18px 8px;
            background: var(--tg-incoming);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
            overflow: hidden;
        }

        .message-row.mine .bubble {
            background: var(--tg-outgoing);
            border-radius: 18px 18px 8px 18px;
        }

        .message-name {
            color: #6ab3ff;
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 4px;
            cursor: pointer;
        }

        .reply-pill {
            margin-bottom: 6px;
            padding: 6px 8px;
            border-left: 2px solid #59aef9;
            background: rgba(255, 255, 255, 0.04);
            border-radius: 10px;
            font-size: 12px;
            color: #c9def2;
            cursor: pointer;
        }

        .reply-pill:hover {
            background: rgba(255, 255, 255, 0.08);
        }

        .message-text {
            white-space: pre-wrap;
            word-break: break-word;
            font-size: 14px;
            line-height: 1.45;
        }

        .message-image,
        .message-video {
            display: block;
            margin-top: 8px;
            max-width: min(100%, 180px);
            border-radius: 14px;
        }

        .message-image {
            cursor: zoom-in;
        }

        .message-video-shell {
            margin-top: 8px;
            width: min(100%, 180px);
            aspect-ratio: 4 / 5;
            border-radius: 14px;
            overflow: hidden;
            background: #0a0f15;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.05);
        }

        .message-video {
            width: 100%;
            height: 100%;
            background: #000;
            object-fit: cover;
        }

        .media-link {
            display: inline-block;
            margin-top: 8px;
            color: #8fc9ff;
            font-size: 12px;
            text-decoration: none;
        }

        .media-link:hover {
            text-decoration: underline;
        }

        .media-viewer {
            position: fixed;
            inset: 0;
            z-index: 60;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 20px;
            background: rgba(2, 8, 15, 0.92);
            backdrop-filter: blur(10px);
        }

        .media-viewer.show {
            display: flex;
        }

        .media-viewer-dialog {
            position: relative;
            width: min(100%, 980px);
            max-height: min(100%, 92vh);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 16px;
            border-radius: 24px;
            background: rgba(18, 27, 38, 0.96);
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
        }

        .media-viewer-dialog.video-mode {
            width: min(100%, 100vw);
            max-width: 100vw;
            max-height: 100vh;
            height: 100vh;
            border-radius: 0;
            padding: 24px;
            background: rgba(4, 10, 18, 0.98);
            border: none;
            box-shadow: none;
        }

        .media-viewer-image,
        .media-viewer-video {
            max-width: 100%;
            max-height: calc(92vh - 64px);
            border-radius: 18px;
            display: block;
            background: #000;
        }

        .media-viewer-dialog.video-mode .media-viewer-video {
            width: 100%;
            max-width: 100%;
            max-height: calc(100vh - 48px);
            border-radius: 18px;
        }

        .media-viewer-close {
            position: absolute;
            top: 12px;
            right: 12px;
            width: 40px;
            height: 40px;
            border: none;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
            font-size: 22px;
            line-height: 1;
            cursor: pointer;
        }

        .media-viewer-close:hover {
            background: rgba(255, 255, 255, 0.18);
        }

        .editor-modal {
            position: fixed;
            inset: 0;
            z-index: 70;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 16px;
            background: rgba(5, 10, 18, 0.92);
            backdrop-filter: blur(10px);
        }

        .editor-modal.show {
            display: flex;
        }

        .editor-card {
            width: min(100%, 860px);
            max-height: 92vh;
            overflow: auto;
            padding: 14px;
            border-radius: 24px;
            background: rgba(23, 33, 43, 0.98);
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
        }

        .editor-title {
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 10px;
        }

        .editor-canvas-wrap {
            border-radius: 18px;
            overflow: hidden;
            background: #0a0f15;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .editor-canvas {
            display: block;
            width: 100%;
            max-height: 62vh;
            touch-action: none;
            background: #0a0f15;
        }

        .editor-actions {
            margin-top: 12px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        .consent-modal {
            position: fixed;
            inset: 0;
            z-index: 75;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 16px;
            background: rgba(5, 10, 18, 0.92);
            backdrop-filter: blur(10px);
        }

        .consent-modal.show {
            display: flex;
        }

        .consent-card {
            width: min(100%, 520px);
            padding: 18px;
            border-radius: 24px;
            background: rgba(23, 33, 43, 0.98);
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
        }

        .consent-title {
            font-size: 17px;
            font-weight: 700;
            margin-bottom: 10px;
        }

        .consent-text {
            font-size: 14px;
            line-height: 1.5;
            color: #d9e6f2;
        }

        .consent-actions {
            margin-top: 14px;
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        }

        .consent-btn {
            border: none;
            border-radius: 14px;
            padding: 10px 14px;
            font: inherit;
            cursor: pointer;
        }

        .consent-btn.primary {
            background: linear-gradient(135deg, #2ea6ff, #1b7fd0);
            color: #fff;
        }

        .consent-btn.secondary {
            background: rgba(255, 255, 255, 0.08);
            color: #d8e6f3;
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

        .author-badge {
            display: inline-flex;
            align-items: center;
            margin-left: 6px;
            padding: 2px 6px;
            border-radius: 999px;
            background: rgba(46, 166, 255, 0.14);
            color: #8fd1ff;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            vertical-align: middle;
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
            max-width: calc(100vw - 32px);
        }

        .composer {
            position: fixed;
            left: 50%;
            bottom: -2px;
            transform: translateX(-50%);
            width: min(760px, 100%);
            padding: 10px 8px calc(10px + env(safe-area-inset-bottom));
            background: transparent;
        }

        .composer-card {
            background: transparent;
            border: none;
            border-radius: 0;
            padding: 0;
            box-shadow: none;
        }

        .reply-box {
            display: none;
            margin-bottom: 6px;
            padding: 8px 10px;
            border-radius: 14px;
            background: #223140;
            font-size: 12px;
            color: #cfe5fb;
        }

        .reply-box.show {
            display: block;
        }

        .composer-entry {
            display: flex;
            align-items: flex-end;
            gap: 10px;
        }

        textarea {
            width: 100%;
            min-height: 40px;
            height: 40px;
            max-height: 120px;
            resize: none;
            background: rgba(34, 49, 64, 0.96);
            border: none;
            color: white;
            border-radius: 22px;
            padding: 10px 16px;
            outline: none;
            font: inherit;
            font-size: 14px;
            line-height: 20px;
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.2);
            -webkit-user-select: text;
            user-select: text;
        }

        textarea:focus {
            box-shadow: 0 0 0 1px rgba(46, 166, 255, 0.22), 0 10px 24px rgba(0, 0, 0, 0.22);
        }

        .attachment-row {
            display: flex;
            align-items: center;
            justify-content: flex-start;
            gap: 0;
        }

        .attach-btn {
            border: none;
            background: rgba(34, 49, 64, 0.96);
            color: #cfe4f8;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            flex-shrink: 0;
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.18);
            padding: 0;
        }

        .attach-btn svg {
            width: 18px;
            height: 18px;
            display: block;
        }

        .attach-btn:hover {
            background: rgba(42, 61, 79, 0.98);
        }

        .preview {
            margin: 0 0 8px;
            display: none;
            width: fit-content;
            max-width: 120px;
        }

        .preview.show {
            display: inline-block;
        }

        .preview img,
        .preview video {
            max-width: 72px;
            max-height: 72px;
            border-radius: 12px;
            display: block;
        }

        .preview-video-shell {
            margin-top: 0;
            width: 72px;
            aspect-ratio: 1 / 1;
            border-radius: 12px;
            overflow: hidden;
            background: #0a0f15;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .preview-actions {
            margin-top: 4px;
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        .preview-actions .attach-btn {
            width: auto;
            height: auto;
            border-radius: 12px;
            padding: 6px 10px;
            font-size: 12px;
        }

        .preview-actions .attach-btn svg {
            width: 14px;
            height: 14px;
        }

        .composer-actions {
            margin-top: 4px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }

        .channel-toggle {
            display: none;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            color: #cfe5fb;
            background: rgba(34, 49, 64, 0.82);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 999px;
            padding: 6px 10px;
        }

        .channel-toggle.show {
            display: inline-flex;
        }

        .channel-toggle input {
            accent-color: #2ea6ff;
        }

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
            background: linear-gradient(135deg, #2ea6ff, #1b7fd0);
            color: white;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            flex-shrink: 0;
            box-shadow: 0 10px 24px rgba(24, 126, 208, 0.32);
            padding: 0;
        }

        .send-btn svg {
            width: 17px;
            height: 17px;
            display: block;
        }

        .send-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }

        .context-overlay {
            position: fixed;
            inset: 0;
            z-index: 70;
            display: none;
            padding: 16px;
            background: rgba(3, 10, 18, 0.54);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            align-items: flex-end;
            justify-content: center;
        }

        .context-overlay.show {
            display: flex;
        }

        .context-overlay-inner {
            width: min(100%, 240px);
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: calc(8px + env(safe-area-inset-bottom));
        }

        .context-preview {
            pointer-events: none;
        }

        .context-preview .message-row {
            margin: 0;
        }

        .context-preview .bubble {
            transform: scale(1);
            box-shadow: 0 24px 50px rgba(0, 0, 0, 0.28);
        }

        .context-menu {
            width: 100%;
            padding: 8px;
            border-radius: 24px;
            background: rgba(23, 33, 43, 0.98);
            border: 1px solid var(--tg-panel-border);
            box-shadow: 0 20px 48px rgba(0, 0, 0, 0.35);
        }

        .context-menu button {
            width: 100%;
            display: flex;
            align-items: center;
            gap: 12px;
            text-align: left;
            border: none;
            background: transparent;
            color: #ffffff;
            font: inherit;
            font-size: 15px;
            padding: 12px 14px;
            border-radius: 16px;
            cursor: pointer;
        }

        .context-menu button:hover {
            background: rgba(255, 255, 255, 0.08);
        }

        .context-menu svg {
            width: 18px;
            height: 18px;
            flex-shrink: 0;
            opacity: 0.92;
        }

        .context-menu button.danger {
            color: #ff9d9d;
        }

        .jump-highlight {
            outline: 2px solid rgba(46, 166, 255, 0.95);
            box-shadow: 0 0 0 6px rgba(46, 166, 255, 0.18);
            transition: box-shadow 0.3s ease, outline-color 0.3s ease;
        }

        .bubble.press-anim {
            transform: scale(0.985);
            filter: brightness(1.06);
            transition: transform 0.14s ease, filter 0.14s ease;
        }

        @media (max-width: 640px) {
            .feed {
                padding-left: 8px;
                padding-right: 8px;
            }

            .bubble {
                max-width: calc(100vw - 76px);
            }

            .composer-actions {
                align-items: flex-start;
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <div class="app">
        <header class="topbar">
            <div class="topbar-inner">
                <div class="title">
                    <span class="title-dot"></span>
                    <span>Комментарии</span>
                </div>
                <button class="notify-toggle" id="notifyToggle" type="button" aria-label="Уведомления">
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="18" height="18">
                        <path d="M12 4a4 4 0 0 0-4 4v2.2c0 .7-.2 1.3-.6 1.9L6 14.5V16h12v-1.5l-1.4-2.4a3.8 3.8 0 0 1-.6-1.9V8a4 4 0 0 0-4-4Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="M10 19a2 2 0 0 0 4 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                    </svg>
                </button>
            </div>
        </header>
        <section class="post-card" id="postCard" hidden>
            <div class="post-card-label">Пост</div>
            <div class="post-card-text" id="postCardText"></div>
        </section>
        <main class="feed" id="commentsList"></main>
    </div>

    <div class="composer">
        <div class="composer-card">
            <div class="reply-box" id="replyBox"></div>
            <div class="preview" id="imagePreview">
                <img id="previewImage" alt="preview" hidden>
                <div class="preview-video-shell" id="previewVideoShell" hidden>
                    <video id="previewVideo" controls playsinline hidden></video>
                </div>
                <div class="preview-actions">
                    <button class="attach-btn" id="editImageBtn" type="button" hidden>Редактор фото</button>
                    <button class="attach-btn" id="removeImageBtn" type="button">Убрать вложение</button>
                </div>
            </div>
            <div class="composer-entry">
                <div class="attachment-row">
                    <button class="attach-btn" id="attachBtn" type="button" aria-label="Прикрепить файл">
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M9.5 12.5 16 6a3.5 3.5 0 1 1 5 5l-9 9a5.5 5.5 0 1 1-7.8-7.8l8.3-8.3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                    <input id="imageInput" type="file" accept=".jpg,.jpeg,.png,.gif,.webp,.bmp,.mp4,.mov,.webm,.m4v,image/jpeg,image/png,image/gif,image/webp,image/bmp,video/mp4,video/quicktime,video/webm,video/x-m4v" hidden>
                </div>
                <textarea id="comment" maxlength="1000" placeholder="Сообщение"></textarea>
                <button id="submitBtn" class="send-btn" type="button" aria-label="Отправить">
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M21 3 10 14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="m21 3-7 18-4-7-7-4 18-7Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
            </div>
            <div class="composer-actions">
                <label class="channel-toggle" id="channelToggleWrap">
                    <input id="postAsChannel" type="checkbox">
                    <span id="channelToggleText">От имени канала</span>
                </label>
                <div class="status" id="status"></div>
            </div>
        </div>
    </div>

    <div class="context-overlay" id="contextOverlay" aria-hidden="true">
        <div class="context-overlay-inner">
            <div class="context-preview" id="contextPreview"></div>
            <div class="context-menu" id="contextMenu"></div>
        </div>
    </div>
    <div class="media-viewer" id="mediaViewer" aria-hidden="true">
        <div class="media-viewer-dialog" id="mediaViewerDialog">
            <button class="media-viewer-close" id="mediaViewerClose" type="button" aria-label="Закрыть">×</button>
            <img class="media-viewer-image" id="mediaViewerImage" alt="full media" hidden>
            <video class="media-viewer-video" id="mediaViewerVideo" controls playsinline hidden></video>
        </div>
    </div>
    <div class="editor-modal" id="imageEditorModal" aria-hidden="true">
        <div class="editor-card" id="imageEditorCard">
            <div class="editor-title">Редактор фото</div>
            <div class="editor-canvas-wrap">
                <canvas class="editor-canvas" id="imageEditorCanvas"></canvas>
            </div>
            <div class="editor-actions">
                <button class="attach-btn" id="cropSquareBtn" type="button">Обрезать 1:1</button>
                <button class="attach-btn" id="toggleDrawBtn" type="button">Рисование: выкл</button>
                <button class="attach-btn" id="resetEditorBtn" type="button">Сброс</button>
                <button class="attach-btn" id="applyEditorBtn" type="button">Готово</button>
                <button class="attach-btn" id="closeEditorBtn" type="button">Закрыть</button>
            </div>
        </div>
    </div>
    <div class="consent-modal" id="consentModal" aria-hidden="true">
        <div class="consent-card">
            <div class="consent-title">Согласие на обработку данных</div>
            <div class="consent-text">
                Продолжая использовать комментарии, вы соглашаетесь на обработку имени профиля MAX, текста комментариев и прикреплённых медиа для работы этого сервиса комментариев.
            </div>
            <div class="consent-actions">
                <button class="consent-btn secondary" id="consentDeclineBtn" type="button">Закрыть</button>
                <button class="consent-btn primary" id="consentAcceptBtn" type="button">Согласен</button>
            </div>
        </div>
    </div>

    <script src="https://st.max.ru/js/max-web-app.js"></script>
    <script>
        const commentsList = document.getElementById("commentsList");
        const commentInput = document.getElementById("comment");
        const status = document.getElementById("status");
        const submitBtn = document.getElementById("submitBtn");
        const attachBtn = document.getElementById("attachBtn");
        const imageInput = document.getElementById("imageInput");
        const imagePreview = document.getElementById("imagePreview");
        const previewImage = document.getElementById("previewImage");
        const previewVideo = document.getElementById("previewVideo");
        const previewVideoShell = document.getElementById("previewVideoShell");
        const removeImageBtn = document.getElementById("removeImageBtn");
        const editImageBtn = document.getElementById("editImageBtn");
        const channelToggleWrap = document.getElementById("channelToggleWrap");
        const channelToggleText = document.getElementById("channelToggleText");
        const postAsChannel = document.getElementById("postAsChannel");
        const postCard = document.getElementById("postCard");
        const postCardText = document.getElementById("postCardText");
        const replyBox = document.getElementById("replyBox");
        const contextOverlay = document.getElementById("contextOverlay");
        const contextPreview = document.getElementById("contextPreview");
        const contextMenu = document.getElementById("contextMenu");
        const composer = document.querySelector(".composer");
        const notifyToggle = document.getElementById("notifyToggle");
        const mediaViewer = document.getElementById("mediaViewer");
        const mediaViewerDialog = document.getElementById("mediaViewerDialog");
        const mediaViewerImage = document.getElementById("mediaViewerImage");
        const mediaViewerVideo = document.getElementById("mediaViewerVideo");
        const mediaViewerClose = document.getElementById("mediaViewerClose");
        const imageEditorModal = document.getElementById("imageEditorModal");
        const imageEditorCard = document.getElementById("imageEditorCard");
        const imageEditorCanvas = document.getElementById("imageEditorCanvas");
        const cropSquareBtn = document.getElementById("cropSquareBtn");
        const toggleDrawBtn = document.getElementById("toggleDrawBtn");
        const resetEditorBtn = document.getElementById("resetEditorBtn");
        const applyEditorBtn = document.getElementById("applyEditorBtn");
        const closeEditorBtn = document.getElementById("closeEditorBtn");
        const consentModal = document.getElementById("consentModal");
        const consentAcceptBtn = document.getElementById("consentAcceptBtn");
        const consentDeclineBtn = document.getElementById("consentDeclineBtn");

        let initData = "";
        let postId = "";
        let currentUser = null;
        let selectedImage = null;
        let editingCommentId = null;
        let replyToCommentId = null;
        let latestComments = [];
        let menuCommentId = null;
        let menuTargetElement = null;
        let longPressTimer = null;
        let currentPreviewObjectUrl = null;
        let editorImage = null;
        let editorBaseDataUrl = "";
        let editorDrawingEnabled = false;
        let editorIsDrawing = false;
        let editorLastPoint = null;
        let notificationSettings = { notifications_enabled: true };
        let lastCommentsRenderSignature = "";
        let lastRenderedPostText = "";
        const allowedImageTypes = new Set(["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"]);
        const allowedVideoTypes = new Set(["video/mp4", "video/quicktime", "video/webm", "video/x-m4v"]);
        const allowedExtensions = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".mp4", ".mov", ".webm", ".m4v"];

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

        function getConsentStorageKey() {
            const userId = currentUser && currentUser.user_id ? String(currentUser.user_id) : "anonymous";
            return `max-comments-consent:${userId}`;
        }

        function syncConsentCache(value) {
            try {
                if (value) {
                    window.localStorage.setItem(getConsentStorageKey(), "1");
                } else {
                    window.localStorage.removeItem(getConsentStorageKey());
                }
            } catch (error) {}
        }

        function hasCachedConsent() {
            try {
                return window.localStorage.getItem(getConsentStorageKey()) === "1";
            } catch (error) {
                return false;
            }
        }

        function buildMenuButton(label, iconPath, action, extraClass = "") {
            return `<button type="button" class="${extraClass}" onclick="${action}"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true">${iconPath}</svg><span>${label}</span></button>`;
        }

        function updateNotifyToggle() {
            if (!notifyToggle) return;
            const enabled = Boolean(notificationSettings && notificationSettings.notifications_enabled);
            notifyToggle.classList.toggle("active", enabled);
            notifyToggle.title = enabled ? "Уведомления включены" : "Уведомления выключены";
        }

        function updateChannelToggle(postInfo) {
            const canPostAsChannel = Boolean(postInfo && postInfo.viewer_can_post_as_channel);
            if (!channelToggleWrap || !postAsChannel) return;
            channelToggleWrap.classList.toggle("show", canPostAsChannel);
            if (!canPostAsChannel) {
                postAsChannel.checked = false;
                channelToggleText.textContent = "От имени канала";
                return;
            }
            const channelTitle = String(postInfo && postInfo.channel_title ? postInfo.channel_title : "канала");
            channelToggleText.textContent = `От имени: ${channelTitle}`;
        }

        function buildCommentsSignature(comments) {
            return (comments || []).map((comment) => [
                comment.id,
                comment.edited_at || "",
                comment.created_at || "",
                comment.comment || "",
                comment.image_url || "",
                comment.media_type || "",
                comment.avatar_url || "",
                comment.public_username || "",
                comment.can_edit ? "1" : "0",
                comment.can_delete ? "1" : "0"
            ].join("|")).join("::");
        }

        async function loadSettings() {
            if (!initData) return;
            try {
                const url = new URL("/api/settings", window.location.origin);
                url.searchParams.set("init_data", initData);
                const response = await fetch(url);
                const data = await response.json();
                if (response.ok && data.settings) {
                    notificationSettings = {
                        notifications_enabled: Boolean(data.settings.notifications_enabled),
                        consent_accepted: Boolean(data.settings.consent_accepted),
                    };
                    syncConsentCache(notificationSettings.consent_accepted);
                    updateNotifyToggle();
                }
            } catch (error) {
                console.error(error);
            }
        }

        async function toggleNotifications() {
            if (!initData) return;
            const nextValue = !Boolean(notificationSettings && notificationSettings.notifications_enabled);
            try {
                const response = await fetch("/api/settings/notifications", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ init_data: initData, enabled: nextValue })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Не удалось обновить уведомления");
                notificationSettings.notifications_enabled = Boolean(data.notifications_enabled);
                updateNotifyToggle();
            } catch (error) {
                showStatus(error.message || "Ошибка уведомлений", "error");
            }
        }

        function openProfileLink(publicUsername) {
            const username = String(publicUsername || "").trim();
            if (!username) return;
            window.open(`https://max.ru/${username}`, "_blank", "noopener");
        }

        function hasConsent() {
            return Boolean((notificationSettings && notificationSettings.consent_accepted) || hasCachedConsent());
        }

        function openConsentModal() {
            consentModal.classList.add("show");
            consentModal.setAttribute("aria-hidden", "false");
            document.body.style.overflow = "hidden";
        }

        function closeConsentModal() {
            consentModal.classList.remove("show");
            consentModal.setAttribute("aria-hidden", "true");
            document.body.style.overflow = mediaViewer.classList.contains("show") || imageEditorModal.classList.contains("show") ? "hidden" : "";
        }

        async function acceptConsent() {
            if (!initData) return;
            try {
                const response = await fetch("/api/settings/consent", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ init_data: initData, accepted: true })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Не удалось сохранить согласие");
                notificationSettings.consent_accepted = Boolean(data.consent_accepted);
                syncConsentCache(notificationSettings.consent_accepted);
            } catch (error) {
                showStatus(error.message || "Ошибка согласия", "error");
                return;
            }
            closeConsentModal();
        }

        function revokePreviewObjectUrl() {
            if (currentPreviewObjectUrl) {
                URL.revokeObjectURL(currentPreviewObjectUrl);
                currentPreviewObjectUrl = null;
            }
        }

        function hasAllowedExtension(file) {
            const name = (file && file.name ? file.name.toLowerCase() : "");
            return allowedExtensions.some((ext) => name.endsWith(ext));
        }

        function isAllowedMediaFile(file) {
            const fileType = (file && file.type ? file.type.toLowerCase() : "");
            return allowedImageTypes.has(fileType) || allowedVideoTypes.has(fileType) || hasAllowedExtension(file);
        }

        function loadImageElement(file) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onerror = () => reject(new Error("Не удалось прочитать изображение"));
                reader.onload = () => {
                    const image = new Image();
                    image.onload = () => resolve(image);
                    image.onerror = () => reject(new Error("Не удалось обработать изображение"));
                    image.src = reader.result;
                };
                reader.readAsDataURL(file);
            });
        }

        async function compressImageFile(file) {
            const fileType = (file.type || "").toLowerCase();
            if (!fileType.startsWith("image/") || fileType === "image/gif" || file.size < 900_000) {
                return file;
            }

            const image = await loadImageElement(file);
            const maxWidth = 1600;
            const maxHeight = 1600;
            const scale = Math.min(1, maxWidth / image.width, maxHeight / image.height);
            const width = Math.max(1, Math.round(image.width * scale));
            const height = Math.max(1, Math.round(image.height * scale));
            const canvas = document.createElement("canvas");
            canvas.width = width;
            canvas.height = height;
            const context = canvas.getContext("2d", { alpha: false });
            context.drawImage(image, 0, 0, width, height);

            const blob = await new Promise((resolve) => {
                canvas.toBlob(resolve, "image/jpeg", 0.76);
            });
            if (!blob || blob.size >= file.size) {
                return file;
            }
            const safeName = (file.name || "photo").replace(/\\.[^.]+$/, "") + ".jpg";
            return new File([blob], safeName, { type: "image/jpeg", lastModified: Date.now() });
        }

        function drawEditorImage() {
            if (!editorImage) return;
            const ratio = editorImage.height / editorImage.width;
            imageEditorCanvas.width = Math.max(1, editorImage.width);
            imageEditorCanvas.height = Math.max(1, editorImage.height);
            imageEditorCanvas.style.aspectRatio = `${editorImage.width} / ${editorImage.height}`;
            const context = imageEditorCanvas.getContext("2d");
            context.clearRect(0, 0, imageEditorCanvas.width, imageEditorCanvas.height);
            context.drawImage(editorImage, 0, 0, imageEditorCanvas.width, imageEditorCanvas.height);
        }

        function openImageEditor() {
            if (!selectedImage || !(selectedImage.type || "").startsWith("image/")) return;
            const reader = new FileReader();
            reader.onload = () => {
                editorBaseDataUrl = reader.result;
                editorImage = new Image();
                editorImage.onload = () => {
                    drawEditorImage();
                    imageEditorModal.classList.add("show");
                    imageEditorModal.setAttribute("aria-hidden", "false");
                    document.body.style.overflow = "hidden";
                };
                editorImage.src = editorBaseDataUrl;
            };
            reader.readAsDataURL(selectedImage);
        }

        function closeImageEditor() {
            imageEditorModal.classList.remove("show");
            imageEditorModal.setAttribute("aria-hidden", "true");
            editorIsDrawing = false;
            editorLastPoint = null;
            editorDrawingEnabled = false;
            toggleDrawBtn.textContent = "Рисование: выкл";
            document.body.style.overflow = mediaViewer.classList.contains("show") ? "hidden" : "";
        }

        function getCanvasPoint(event) {
            const rect = imageEditorCanvas.getBoundingClientRect();
            const source = event.touches && event.touches[0] ? event.touches[0] : event;
            const x = ((source.clientX - rect.left) / rect.width) * imageEditorCanvas.width;
            const y = ((source.clientY - rect.top) / rect.height) * imageEditorCanvas.height;
            return { x, y };
        }

        function startCanvasDraw(event) {
            if (!editorDrawingEnabled) return;
            editorIsDrawing = true;
            editorLastPoint = getCanvasPoint(event);
            event.preventDefault();
        }

        function moveCanvasDraw(event) {
            if (!editorDrawingEnabled || !editorIsDrawing || !editorLastPoint) return;
            const point = getCanvasPoint(event);
            const context = imageEditorCanvas.getContext("2d");
            context.strokeStyle = "#ff4d4f";
            context.lineWidth = Math.max(4, imageEditorCanvas.width / 120);
            context.lineCap = "round";
            context.lineJoin = "round";
            context.beginPath();
            context.moveTo(editorLastPoint.x, editorLastPoint.y);
            context.lineTo(point.x, point.y);
            context.stroke();
            editorLastPoint = point;
            event.preventDefault();
        }

        function stopCanvasDraw() {
            editorIsDrawing = false;
            editorLastPoint = null;
        }

        function cropEditorToSquare() {
            if (!editorImage) return;
            const context = imageEditorCanvas.getContext("2d");
            const side = Math.min(imageEditorCanvas.width, imageEditorCanvas.height);
            const x = Math.floor((imageEditorCanvas.width - side) / 2);
            const y = Math.floor((imageEditorCanvas.height - side) / 2);
            const cropped = document.createElement("canvas");
            cropped.width = side;
            cropped.height = side;
            cropped.getContext("2d").drawImage(imageEditorCanvas, x, y, side, side, 0, 0, side, side);
            editorBaseDataUrl = cropped.toDataURL("image/jpeg", 0.9);
            editorImage = new Image();
            editorImage.onload = drawEditorImage;
            editorImage.src = editorBaseDataUrl;
        }

        async function applyImageEditor() {
            const blob = await new Promise((resolve) => imageEditorCanvas.toBlob(resolve, "image/jpeg", 0.82));
            if (!blob) return;
            const safeName = ((selectedImage && selectedImage.name) || "photo").replace(/\\.[^.]+$/, "") + ".jpg";
            selectedImage = new File([blob], safeName, { type: "image/jpeg", lastModified: Date.now() });
            setPreviewFromFile(selectedImage);
            closeImageEditor();
            showStatus("Фото обновлено", "success");
        }

        function syncComposerSpace() {
            const height = composer ? composer.offsetHeight : 120;
            document.documentElement.style.setProperty("--composer-space", `${height}px`);
        }

        function closeMediaViewer() {
            mediaViewer.classList.remove("show");
            mediaViewer.setAttribute("aria-hidden", "true");
            mediaViewerDialog.classList.remove("video-mode");
            mediaViewerImage.removeAttribute("src");
            mediaViewerImage.hidden = true;
            mediaViewerImage.style.display = "none";
            mediaViewerVideo.pause();
            mediaViewerVideo.removeAttribute("src");
            mediaViewerVideo.hidden = true;
            mediaViewerVideo.style.display = "none";
            mediaViewerVideo.load();
            document.body.style.overflow = "";
        }

        function normalizeMediaType(mediaType, url) {
            const type = String(mediaType || "").toLowerCase();
            if (type === "image" || type === "video") {
                return type;
            }
            const safeUrl = String(url || "").toLowerCase();
            if (safeUrl.match(/\\.(mp4|mov|webm|m4v)(\\?|$)/)) {
                return "video";
            }
            return "image";
        }

        function openMediaViewer(url, mediaType) {
            if (!url) return;
            const normalizedType = normalizeMediaType(mediaType, url);
            const isVideo = normalizedType === "video";
            mediaViewerDialog.classList.toggle("video-mode", isVideo);
            mediaViewerImage.removeAttribute("src");
            mediaViewerVideo.pause();
            mediaViewerVideo.removeAttribute("src");
            mediaViewerVideo.load();
            mediaViewerImage.hidden = isVideo;
            mediaViewerImage.style.display = isVideo ? "none" : "block";
            mediaViewerVideo.hidden = !isVideo;
            mediaViewerVideo.style.display = isVideo ? "block" : "none";
            if (isVideo) {
                mediaViewerVideo.src = url;
                mediaViewerVideo.load();
            } else {
                mediaViewerImage.src = url;
            }
            mediaViewer.classList.add("show");
            mediaViewer.setAttribute("aria-hidden", "false");
            document.body.style.overflow = "hidden";
        }

        function jumpToComment(commentId) {
            const node = document.querySelector(`.bubble[data-comment-id="${commentId}"]`);
            if (!node) return;
            node.scrollIntoView({ behavior: "smooth", block: "center" });
            node.classList.add("jump-highlight");
            setTimeout(() => node.classList.remove("jump-highlight"), 1300);
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
            revokePreviewObjectUrl();
            if (!file) {
                imagePreview.classList.remove("show");
                previewImage.removeAttribute("src");
                previewImage.hidden = true;
                previewImage.style.display = "none";
                previewVideoShell.hidden = true;
                previewVideoShell.style.display = "none";
                previewVideo.pause();
                previewVideo.removeAttribute("src");
                previewVideo.hidden = true;
                previewVideo.style.display = "none";
                previewVideo.load();
                editImageBtn.hidden = true;
                editImageBtn.style.display = "none";
                return;
            }
            const isVideo = (file.type || "").startsWith("video/");
            previewImage.removeAttribute("src");
            previewImage.hidden = isVideo;
            previewImage.style.display = isVideo ? "none" : "block";
            previewVideoShell.hidden = !isVideo;
            previewVideoShell.style.display = isVideo ? "flex" : "none";
            previewVideo.pause();
            previewVideo.removeAttribute("src");
            previewVideo.hidden = !isVideo;
            previewVideo.style.display = isVideo ? "block" : "none";
            editImageBtn.hidden = isVideo;
            editImageBtn.style.display = isVideo ? "none" : "inline-flex";
            if (isVideo) {
                currentPreviewObjectUrl = URL.createObjectURL(file);
                previewVideo.src = currentPreviewObjectUrl;
                previewVideo.preload = "none";
                previewVideo.load();
            } else {
                const reader = new FileReader();
                reader.onload = () => {
                    previewImage.src = reader.result;
                };
                reader.readAsDataURL(file);
            }
            imagePreview.classList.add("show");
        }

        function resetComposer() {
            editingCommentId = null;
            replyToCommentId = null;
            selectedImage = null;
            commentInput.value = "";
            imageInput.value = "";
            imagePreview.classList.remove("show");
            revokePreviewObjectUrl();
            previewImage.removeAttribute("src");
            previewImage.hidden = true;
            previewImage.style.display = "none";
            previewVideoShell.hidden = true;
            previewVideoShell.style.display = "none";
            previewVideo.pause();
            previewVideo.removeAttribute("src");
            previewVideo.hidden = true;
            previewVideo.style.display = "none";
            previewVideo.load();
            editImageBtn.hidden = true;
            editImageBtn.style.display = "none";
            replyBox.classList.remove("show");
            replyBox.textContent = "";
            syncComposerSpace();
        }

        function renderCommentNode(comment, replyMap) {
            const mine = currentUser && comment.user_id === currentUser.user_id;
            const initial = escapeHtml((comment.username || "?").charAt(0).toUpperCase());
            const mediaUrl = comment.image_url ? encodeURI(comment.image_url) : "";
            const normalizedMediaType = normalizeMediaType(comment.media_type, mediaUrl);
            const profileAction = comment.public_username ? `onclick="openProfileLink('${escapeHtml(comment.public_username)}')"` : "";
            const avatarUrl = comment.avatar_url ? encodeURI(comment.avatar_url) : "";
            const authorBadge = comment.author_type === "channel" ? '<span class="author-badge">канал</span>' : "";
            const avatarHtml = avatarUrl
                ? `<div class="avatar" ${profileAction}><img src="${avatarUrl}" alt="${escapeHtml(comment.username)}" loading="lazy" onerror="this.style.display='none'; this.parentElement.textContent='${initial}'"></div>`
                : `<div class="avatar" ${profileAction}>${initial}</div>`;
            const mediaHtml = comment.image_url
                ? (normalizedMediaType === "video"
                    ? `<div class="message-video-shell"><video class="message-video" src="${mediaUrl}" controls playsinline preload="none"></video></div><a class="media-link" href="#" onclick="openMediaViewer('${mediaUrl}', 'video'); return false;">Открыть видео</a>`
                    : `<img class="message-image" src="${mediaUrl}" alt="comment media" loading="lazy" onclick="openMediaViewer('${mediaUrl}', 'image')"><a class="media-link" href="#" onclick="openMediaViewer('${mediaUrl}', 'image'); return false;">Открыть фото</a>`)
                : "";
            const editedHtml = comment.edited_at ? '<span>изменено</span>' : "";
            const parentPreview = comment.parent_preview ? `<div class="reply-pill" onclick="jumpToComment(${comment.parent_id})">Ответ для ${escapeHtml(comment.parent_preview.username)}: ${escapeHtml(comment.parent_preview.comment)}</div>` : "";
            return `
                <div class="message-thread">
                    <div class="message-row ${mine ? "mine" : ""}">
                        ${mine ? "" : avatarHtml}
                        <div class="bubble" data-comment-id="${comment.id}">
                            <div class="message-name" ${profileAction}>${escapeHtml(comment.username)} ${authorBadge}</div>
                            ${parentPreview}
                            <div class="message-text">${escapeHtml(comment.comment)}</div>
                            ${mediaHtml}
                            <div class="message-meta">
                                ${editedHtml}
                                <span>${formatDate(comment.edited_at || comment.created_at)}</span>
                            </div>
                        </div>
                        ${mine ? avatarHtml : ""}
                    </div>
                </div>
            `;
        }

        function renderComments(comments) {
            latestComments = comments || [];
            if (!latestComments.length) {
                lastCommentsRenderSignature = "";
                commentsList.innerHTML = '<div class="empty">Пока нет комментариев. Можно написать первый.</div>';
                return;
            }

            const sorted = [...latestComments].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
            const signature = buildCommentsSignature(sorted);
            if (signature === lastCommentsRenderSignature) {
                return;
            }
            lastCommentsRenderSignature = signature;
            commentsList.innerHTML = sorted.map((comment) => renderCommentNode(comment, {})).join("");
        }

        async function loadComments() {
            if (!postId) {
                commentsList.innerHTML = '<div class="empty">Не найден startapp для этого поста.</div>';
                return;
            }

            try {
                const url = new URL("/api/comments/" + encodeURIComponent(postId), window.location.origin);
                if (initData) url.searchParams.set("init_data", initData);
                const response = await fetch(url);
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Ошибка загрузки");
                const nextPostText = data.post && data.post.post_text ? data.post.post_text : "";
                if (nextPostText && nextPostText !== lastRenderedPostText) {
                    postCard.hidden = false;
                    postCardText.textContent = nextPostText;
                    lastRenderedPostText = nextPostText;
                } else if (!nextPostText) {
                    postCard.hidden = true;
                    lastRenderedPostText = "";
                }
                updateChannelToggle(data.post || {});
                renderComments(data.comments || []);
                bindContextHandlers();
            } catch (error) {
                commentsList.innerHTML = '<div class="empty">Не удалось загрузить комментарии.</div>';
            }
        }

        async function sendComment() {
            const comment = commentInput.value.trim();
            if (!hasConsent()) {
                openConsentModal();
                return;
            }
            if (!postId) {
                showStatus("MAX не передал startapp", "error");
                return;
            }
            if (!currentUser || !currentUser.user_id) {
                showStatus("Не удалось получить профиль пользователя из MAX", "error");
                return;
            }
            if (!comment && !selectedImage && !editingCommentId) {
                showStatus("Введите комментарий или выберите фото/видео", "error");
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
                    if (postAsChannel && postAsChannel.checked) formData.append("post_as_channel", "1");
                    if (replyToCommentId) formData.append("parent_id", String(replyToCommentId));
                    if (selectedImage) formData.append("image", selectedImage);
                    response = await fetch("/api/comment", { method: "POST", body: formData });
                }

                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Ошибка отправки");
                const wasEditing = Boolean(editingCommentId);
                resetComposer();
                showStatus("", "");
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
            replyBox.classList.remove("show");
            commentInput.focus();
            showStatus("Редактирование комментария", "");
            syncComposerSpace();
        }

        function startReply(commentId) {
            const comment = latestComments.find((item) => item.id === commentId);
            if (!comment) return;
            editingCommentId = null;
            replyToCommentId = commentId;
            replyBox.classList.add("show");
            replyBox.textContent = `Ответ для ${comment.username}: ${comment.comment || "фото"}`;
            commentInput.focus();
            syncComposerSpace();
        }

        function openContextMenu(commentId, targetElement) {
            const comment = latestComments.find((item) => item.id === commentId);
            if (!comment) return;
            const canEdit = Boolean(comment.can_edit);
            const canDelete = Boolean(comment.can_delete);
            menuCommentId = commentId;
            menuTargetElement = targetElement;
            const row = targetElement.closest(".message-row");
            contextPreview.innerHTML = row ? row.outerHTML : "";
            contextMenu.innerHTML = `
                ${buildMenuButton(
                    "Ответить",
                    '<path d="M10 7 4 12l6 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 12h8a6 6 0 0 1 6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
                    "menuReply()"
                )}
                ${buildMenuButton(
                    "Скопировать",
                    '<rect x="9" y="9" width="10" height="10" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M7 15H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
                    "menuCopy()"
                )}
                ${canEdit ? buildMenuButton(
                    "Редактировать",
                    '<path d="m4 20 4.5-1 9-9a2.1 2.1 0 0 0-3-3l-9 9L4 20Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M13.5 7.5 16.5 10.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
                    "menuEdit()"
                ) : ""}
                ${canDelete ? buildMenuButton(
                    "Удалить",
                    '<path d="M5 7h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" stroke="currentColor" stroke-width="1.8"/><path d="M8 7l1 11a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2l1-11" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
                    "menuDelete()",
                    "danger"
                ) : ""}
            `;
            contextOverlay.classList.add("show");
            contextOverlay.setAttribute("aria-hidden", "false");
        }

        function closeContextMenu() {
            contextOverlay.classList.remove("show");
            contextOverlay.setAttribute("aria-hidden", "true");
            contextPreview.innerHTML = "";
            menuCommentId = null;
            menuTargetElement = null;
        }

        function bindContextHandlers() {
            document.querySelectorAll(".bubble[data-comment-id]").forEach((bubble) => {
                const commentId = Number(bubble.dataset.commentId);
                const start = () => {
                    bubble.classList.add("press-anim");
                    clearTimeout(longPressTimer);
                    longPressTimer = setTimeout(() => openContextMenu(commentId, bubble), 450);
                };
                const cancel = () => {
                    bubble.classList.remove("press-anim");
                    clearTimeout(longPressTimer);
                };
                const contextOpen = (event) => {
                    event.preventDefault();
                    cancel();
                    openContextMenu(commentId, bubble);
                };
                bubble.onclick = () => {
                    bubble.classList.add("press-anim");
                    setTimeout(() => bubble.classList.remove("press-anim"), 120);
                };
                bubble.onmousedown = start;
                bubble.ontouchstart = start;
                bubble.onmouseup = cancel;
                bubble.onmouseleave = cancel;
                bubble.ontouchend = cancel;
                bubble.ontouchcancel = cancel;
                bubble.oncontextmenu = contextOpen;
            });
        }

        function menuReply() {
            if (!menuCommentId) return;
            const id = menuCommentId;
            closeContextMenu();
            startReply(id);
        }

        function menuEdit() {
            if (!menuCommentId) return;
            const id = menuCommentId;
            closeContextMenu();
            startEdit(id);
        }

        async function menuCopy() {
            if (!menuCommentId) return;
            const comment = latestComments.find((item) => item.id === menuCommentId);
            if (!comment) return;
            const copyText = (comment.comment || "").trim() || (comment.media_type === "video" ? "Видео" : "Фото");
            closeContextMenu();
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(copyText);
                    showStatus("Комментарий скопирован", "success");
                    return;
                }
            } catch (error) {}
            const fallback = document.createElement("textarea");
            fallback.value = copyText;
            fallback.setAttribute("readonly", "");
            fallback.style.position = "fixed";
            fallback.style.opacity = "0";
            document.body.appendChild(fallback);
            fallback.select();
            document.execCommand("copy");
            document.body.removeChild(fallback);
            showStatus("Комментарий скопирован", "success");
        }

        async function menuDelete() {
            if (!menuCommentId) return;
            const id = menuCommentId;
            closeContextMenu();
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
            await loadSettings();

            commentInput.addEventListener("input", () => {
                syncComposerSpace();
            });
            commentInput.addEventListener("keydown", (event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                    event.preventDefault();
                    sendComment();
                }
            });
            submitBtn.addEventListener("click", sendComment);
            notifyToggle.addEventListener("click", toggleNotifications);
            attachBtn.addEventListener("click", () => imageInput.click());
            editImageBtn.addEventListener("click", openImageEditor);
            imageInput.addEventListener("change", async () => {
                const pickedFile = imageInput.files && imageInput.files[0] ? imageInput.files[0] : null;
                if (!pickedFile) {
                    selectedImage = null;
                    setPreviewFromFile(null);
                    return;
                }
                if (!isAllowedMediaFile(pickedFile)) {
                    selectedImage = null;
                    imageInput.value = "";
                    setPreviewFromFile(null);
                    showStatus("Разрешены только фото JPG, PNG, GIF, WEBP, BMP и видео MP4, MOV, WEBM, M4V", "error");
                    return;
                }
                try {
                    showStatus("Готовим вложение...", "");
                    selectedImage = await compressImageFile(pickedFile);
                    setPreviewFromFile(selectedImage);
                    if ((selectedImage.type || "").startsWith("video/")) {
                        showStatus("Видео прикреплено", "success");
                    } else {
                        showStatus("Фото готово", "success");
                    }
                } catch (error) {
                    selectedImage = null;
                    imageInput.value = "";
                    setPreviewFromFile(null);
                    showStatus(error.message || "Не удалось подготовить файл", "error");
                }
            });
            removeImageBtn.addEventListener("click", () => {
                selectedImage = null;
                imageInput.value = "";
                setPreviewFromFile(null);
                syncComposerSpace();
            });
            cropSquareBtn.addEventListener("click", cropEditorToSquare);
            toggleDrawBtn.addEventListener("click", () => {
                editorDrawingEnabled = !editorDrawingEnabled;
                toggleDrawBtn.textContent = `Рисование: ${editorDrawingEnabled ? "вкл" : "выкл"}`;
            });
            resetEditorBtn.addEventListener("click", () => {
                if (!editorBaseDataUrl) return;
                editorImage = new Image();
                editorImage.onload = drawEditorImage;
                editorImage.src = editorBaseDataUrl;
            });
            applyEditorBtn.addEventListener("click", applyImageEditor);
            closeEditorBtn.addEventListener("click", closeImageEditor);
            consentAcceptBtn.addEventListener("click", acceptConsent);
            consentDeclineBtn.addEventListener("click", closeConsentModal);
            consentModal.addEventListener("click", (event) => {
                if (event.target === consentModal) {
                    closeConsentModal();
                }
            });
            imageEditorModal.addEventListener("click", (event) => {
                if (event.target === imageEditorModal) {
                    closeImageEditor();
                }
            });
            imageEditorCard.addEventListener("click", (event) => event.stopPropagation());
            imageEditorCanvas.addEventListener("mousedown", startCanvasDraw);
            imageEditorCanvas.addEventListener("mousemove", moveCanvasDraw);
            imageEditorCanvas.addEventListener("mouseup", stopCanvasDraw);
            imageEditorCanvas.addEventListener("mouseleave", stopCanvasDraw);
            imageEditorCanvas.addEventListener("touchstart", startCanvasDraw, { passive: false });
            imageEditorCanvas.addEventListener("touchmove", moveCanvasDraw, { passive: false });
            imageEditorCanvas.addEventListener("touchend", stopCanvasDraw);
            imageEditorCanvas.addEventListener("touchcancel", stopCanvasDraw);
            contextOverlay.addEventListener("click", (event) => {
                if (event.target === contextOverlay) {
                    closeContextMenu();
                }
            });
            contextMenu.addEventListener("click", (event) => event.stopPropagation());
            mediaViewer.addEventListener("click", (event) => {
                if (event.target === mediaViewer) {
                    closeMediaViewer();
                }
            });
            mediaViewerDialog.addEventListener("click", (event) => {
                event.stopPropagation();
            });
            mediaViewerClose.addEventListener("click", closeMediaViewer);
            document.addEventListener("keydown", (event) => {
                if (event.key === "Escape" && mediaViewer.classList.contains("show")) {
                    closeMediaViewer();
                }
                if (event.key === "Escape" && imageEditorModal.classList.contains("show")) {
                    closeImageEditor();
                }
                if (event.key === "Escape" && contextOverlay.classList.contains("show")) {
                    closeContextMenu();
                }
            });
            window.addEventListener("resize", syncComposerSpace);

            syncComposerSpace();
            await loadComments();
            if (!hasConsent()) {
                openConsentModal();
            }
            setInterval(loadComments, 8000);
        }

        window.menuReply = menuReply;
        window.menuCopy = menuCopy;
        window.menuEdit = menuEdit;
        window.menuDelete = menuDelete;
        window.jumpToComment = jumpToComment;
        window.openMediaViewer = openMediaViewer;
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
    upsert_user_settings(user)
    return jsonify({"user": user})


@app.route("/api/settings")
def get_settings():
    verified_user = validate_max_init_data((request.args.get("init_data") or "").strip())
    if not verified_user:
        return jsonify({"error": "Не удалось подтвердить пользователя MAX"}), 400
    upsert_user_settings(verified_user)
    return jsonify({"settings": get_user_settings(verified_user["user_id"])})


def list_channels(owner_user_id: str | None = None, include_deleted: bool = False) -> list[dict]:
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT channels.chat_id, channels.title, channels.avatar_url, channels.is_blocked, channels.created_at, channels.updated_at,
               COUNT(posts.post_id) AS posts_count
        FROM channels
        LEFT JOIN posts ON posts.source_chat_id = channels.chat_id
        GROUP BY channels.chat_id, channels.title, channels.avatar_url, channels.is_blocked, channels.created_at, channels.updated_at
        ORDER BY channels.updated_at DESC, channels.chat_id DESC
        """
    ).fetchall()
    conn.close()
    channels = [
        {
            "chat_id": row["chat_id"],
            "title": row["title"] or row["chat_id"],
            "avatar_url": row["avatar_url"] or "",
            "is_blocked": bool(row["is_blocked"]),
            "posts_count": int(row["posts_count"] or 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    return [hydrate_channel_info(channel) for channel in channels]


def get_channel_stats(chat_id: str | None = None, period: str = "week", owner_user_id: str | None = None) -> dict:
    normalized_chat_id = str(chat_id or "").strip()
    normalized_period = normalize_stats_period(period)
    days = 30 if normalized_period == "month" else 7
    now = datetime.now(timezone.utc)
    since_dt = now - timedelta(days=days)
    since_iso = since_dt.isoformat()
    conn = get_db_connection()

    if normalized_chat_id:
        channel_filter = " AND posts.source_chat_id = ?"
        channel_params = [normalized_chat_id]
        channel = hydrate_channel_info(get_channel_info(normalized_chat_id) or {
            "chat_id": normalized_chat_id,
            "title": normalized_chat_id,
            "avatar_url": "",
            "is_blocked": False,
        })
    else:
        channel_filter = ""
        channel_params = []
        channel = None

    posts_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS posts_count,
            SUM(CASE WHEN counter_enabled = 1 THEN 1 ELSE 0 END) AS counter_enabled_posts_count
        FROM posts
        WHERE created_at >= ? {channel_filter}
        """,
        [since_iso, *channel_params],
    ).fetchone()

    comments_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS comments_count,
            COUNT(DISTINCT comments.user_id) AS unique_commenters,
            SUM(CASE WHEN comments.parent_id IS NOT NULL THEN 1 ELSE 0 END) AS replies_count,
            SUM(CASE WHEN TRIM(COALESCE(comments.media_path, '')) <> '' THEN 1 ELSE 0 END) AS media_comments_count,
            SUM(CASE WHEN comments.author_type = 'channel' THEN 1 ELSE 0 END) AS channel_comments_count
        FROM comments
        JOIN posts ON posts.post_id = comments.post_id
        WHERE comments.created_at >= ? {channel_filter}
        """,
        [since_iso, *channel_params],
    ).fetchone()

    lifetime_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS comments_total,
            COUNT(DISTINCT comments.user_id) AS commenters_total
        FROM comments
        JOIN posts ON posts.post_id = comments.post_id
        WHERE 1 = 1 {channel_filter}
        """,
        channel_params,
    ).fetchone()

    active_channels_row = conn.execute(
        """
        SELECT COUNT(DISTINCT source_chat_id) AS active_channels
        FROM posts
        WHERE created_at >= ? AND TRIM(COALESCE(source_chat_id, '')) <> ''
        """,
        [since_iso],
    ).fetchone()

    top_posts_rows = conn.execute(
        f"""
        SELECT
            posts.post_id,
            posts.source_post_id,
            posts.post_text,
            posts.message_text,
            COUNT(comments.id) AS comments_count,
            MAX(comments.created_at) AS last_comment_at
        FROM posts
        LEFT JOIN comments
            ON comments.post_id = posts.post_id
           AND comments.created_at >= ?
        WHERE 1 = 1 {channel_filter}
        GROUP BY posts.post_id, posts.source_post_id, posts.post_text, posts.message_text
        HAVING comments_count > 0
        ORDER BY comments_count DESC, last_comment_at DESC
        LIMIT 5
        """,
        [since_iso, *channel_params],
    ).fetchall()

    top_commenters_rows = conn.execute(
        f"""
        SELECT
            comments.user_id,
            comments.username,
            comments.author_type,
            COUNT(*) AS comments_count,
            MAX(comments.created_at) AS last_comment_at
        FROM comments
        JOIN posts ON posts.post_id = comments.post_id
        WHERE comments.created_at >= ? {channel_filter}
        GROUP BY comments.user_id, comments.username, comments.author_type
        ORDER BY comments_count DESC, last_comment_at DESC
        LIMIT 5
        """,
        [since_iso, *channel_params],
    ).fetchall()

    activity_rows = conn.execute(
        f"""
        SELECT
            SUBSTR(comments.created_at, 1, 10) AS day,
            COUNT(*) AS comments_count
        FROM comments
        JOIN posts ON posts.post_id = comments.post_id
        WHERE comments.created_at >= ? {channel_filter}
        GROUP BY SUBSTR(comments.created_at, 1, 10)
        ORDER BY day ASC
        """,
        [since_iso, *channel_params],
    ).fetchall()
    conn.close()

    posts_count = int((posts_row["posts_count"] or 0) if posts_row else 0)
    comments_count = int((comments_row["comments_count"] or 0) if comments_row else 0)
    unique_commenters = int((comments_row["unique_commenters"] or 0) if comments_row else 0)
    replies_count = int((comments_row["replies_count"] or 0) if comments_row else 0)
    media_comments_count = int((comments_row["media_comments_count"] or 0) if comments_row else 0)
    channel_comments_count = int((comments_row["channel_comments_count"] or 0) if comments_row else 0)
    counter_enabled_posts_count = int((posts_row["counter_enabled_posts_count"] or 0) if posts_row else 0)
    comments_total = int((lifetime_row["comments_total"] or 0) if lifetime_row else 0)
    commenters_total = int((lifetime_row["commenters_total"] or 0) if lifetime_row else 0)
    active_channels = int((active_channels_row["active_channels"] or 0) if active_channels_row else 0)

    activity_map = {str(row["day"]): int(row["comments_count"] or 0) for row in activity_rows}
    activity_by_day = []
    for offset in range(days):
        day = (since_dt + timedelta(days=offset)).date().isoformat()
        activity_by_day.append({"day": day, "comments_count": activity_map.get(day, 0)})

    top_posts = [
        {
            "post_id": row["post_id"],
            "source_post_id": row["source_post_id"],
            "label": _safe_post_label(row),
            "comments_count": int(row["comments_count"] or 0),
            "last_comment_at": row["last_comment_at"] or "",
        }
        for row in top_posts_rows
    ]
    top_commenters = [
        {
            "user_id": row["user_id"],
            "username": row["username"] or "Пользователь",
            "author_type": row["author_type"] or "user",
            "comments_count": int(row["comments_count"] or 0),
            "last_comment_at": row["last_comment_at"] or "",
        }
        for row in top_commenters_rows
    ]

    avg_comments_per_post = round(comments_count / posts_count, 2) if posts_count else 0.0
    active_days = sum(1 for item in activity_by_day if item["comments_count"] > 0)

    return {
        "period": normalized_period,
        "days": days,
        "scope": "channel" if normalized_chat_id else "all",
        "generated_at": now.isoformat(),
        "since": since_dt.isoformat(),
        "channel": channel,
        "summary": {
            "posts_count": posts_count,
            "counter_enabled_posts_count": counter_enabled_posts_count,
            "comments_count": comments_count,
            "comments_total": comments_total,
            "unique_commenters": unique_commenters,
            "commenters_total": commenters_total,
            "replies_count": replies_count,
            "media_comments_count": media_comments_count,
            "channel_comments_count": channel_comments_count,
            "avg_comments_per_post": avg_comments_per_post,
            "active_days": active_days,
            "active_channels": active_channels,
        },
        "top_posts": top_posts,
        "top_commenters": top_commenters,
        "activity_by_day": activity_by_day,
    }


@app.route("/api/settings/notifications", methods=["POST"])
def update_notifications():
    payload = request.get_json(silent=True) or {}
    verified_user = validate_max_init_data(payload.get("init_data", ""))
    if not verified_user:
        return jsonify({"error": "Не удалось подтвердить пользователя MAX"}), 400
    enabled = bool(payload.get("enabled", True))
    upsert_user_settings(verified_user, 1 if enabled else 0)
    sync_store_db("settings-update")
    update_store_archive("settings-update")
    create_backup("settings-update")
    return jsonify({"status": "success", "notifications_enabled": enabled})


@app.route("/api/settings/consent", methods=["POST"])
def update_consent():
    payload = request.get_json(silent=True) or {}
    verified_user = validate_max_init_data(payload.get("init_data", ""))
    if not verified_user:
        return jsonify({"error": "Не удалось подтвердить пользователя MAX"}), 400
    accepted = bool(payload.get("accepted", True))
    upsert_user_settings(verified_user, consent_accepted=1 if accepted else 0)
    sync_store_db("consent-update")
    update_store_archive("consent-update")
    create_backup("consent-update")
    return jsonify({"status": "success", "consent_accepted": accepted})


@app.route("/api/post", methods=["POST"])
def register_post():
    payload = request.get_json(silent=True) or {}
    post_id = normalize_post_id(payload.get("post_id"))
    source_post_id = str(payload.get("source_post_id") or "").strip()[:256]
    source_chat_id = str(payload.get("source_chat_id") or "").strip()[:256]
    button_message_id = str(payload.get("button_message_id") or "").strip()[:256]
    counter_enabled = 1 if payload.get("counter_enabled", True) else 0
    post_text = (payload.get("post_text") or "").strip()[:4000]
    message_text = (payload.get("message_text") or "").strip()[:4000]
    channel_title = (payload.get("channel_title") or "").strip()[:255]
    channel_avatar_url = (payload.get("channel_avatar_url") or "").strip()[:1000]
    attachments_json = payload.get("attachments") or []
    if not isinstance(attachments_json, list):
        attachments_json = []
    if not post_id:
        return jsonify({"error": "Не переданы данные поста"}), 400
    if source_chat_id:
        chat_info = fetch_chat_info(source_chat_id) if not channel_title else None
        upsert_channel(
            source_chat_id,
            title=channel_title or (chat_info or {}).get("title", ""),
            avatar_url=channel_avatar_url or (chat_info or {}).get("avatar_url", ""),
        )
        channel = get_channel_info(source_chat_id)
        if channel and channel.get("is_blocked"):
            return jsonify({"error": "Канал заблокирован"}), 403

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO posts (post_id, source_post_id, source_chat_id, button_message_id, counter_enabled, post_text, message_text, attachments_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            source_post_id = excluded.source_post_id,
            source_chat_id = excluded.source_chat_id,
            button_message_id = excluded.button_message_id,
            counter_enabled = excluded.counter_enabled,
            post_text = excluded.post_text,
            message_text = excluded.message_text,
            attachments_json = excluded.attachments_json
        """,
        (post_id, source_post_id, source_chat_id, button_message_id, counter_enabled, post_text, message_text, json.dumps(attachments_json, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    sync_store_db("post-upsert")
    update_store_archive("post-upsert")
    create_backup("post-upsert")
    return jsonify({"status": "success"})


@app.route("/api/comments/<path:post_id>")
def get_comments_by_post(post_id):
    normalized_post_id = resolve_post_id(post_id)
    if not normalized_post_id:
        return jsonify({"error": "?? ??????? post_id"}), 400

    verified_user = validate_max_init_data((request.args.get("init_data") or "").strip())
    viewer_id = str((verified_user or {}).get("user_id") or "").strip()
    viewer_is_admin = user_can_moderate_comment(viewer_id, normalized_post_id) if viewer_id else False

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT comments.id, comments.post_id, comments.user_id, comments.username, comments.author_type, comments.channel_chat_id, comments.comment, comments.image_path, comments.media_path, comments.media_type, comments.parent_id, comments.edited_at, comments.created_at
        , COALESCE(comments.public_username, user_settings.public_username) AS public_username
        , COALESCE(comments.avatar_url, user_settings.avatar_url) AS avatar_url
        FROM comments
        LEFT JOIN user_settings ON user_settings.user_id = comments.user_id
        WHERE comments.post_id = ?
        ORDER BY comments.created_at DESC
        """,
        (normalized_post_id,),
    ).fetchall()
    conn.close()

    row_lookup = {row["id"]: row for row in rows}
    comments = []
    for row in rows:
        comment = serialize_comment(row, row_lookup)
        is_owner = bool(viewer_id and str(row["user_id"]) == viewer_id)
        comment["can_edit"] = is_owner
        comment["can_delete"] = is_owner or viewer_is_admin
        comments.append(comment)
    post_info = get_post_info(normalized_post_id)
    if not post_info and rows:
        post_info = build_placeholder_post_info(normalized_post_id, source_post_id=post_id)
    post_info = post_info or {}
    post_info["viewer_can_post_as_channel"] = bool(viewer_is_admin and post_info.get("source_chat_id"))
    return jsonify({"post_id": normalized_post_id, "post": post_info, "comments": comments})


@app.route("/api/post_count/<path:post_id>")
def get_post_count(post_id):
    normalized_post_id = resolve_post_id(post_id)
    if not normalized_post_id:
        return jsonify({"error": "Не передан post_id"}), 400
    conn = get_db_connection()
    row = conn.execute("SELECT COUNT(*) AS count FROM comments WHERE post_id = ?", (normalized_post_id,)).fetchone()
    conn.close()
    return jsonify({"post_id": normalized_post_id, "count": row["count"]})


@app.route("/api/comment", methods=["POST"])
def add_comment():
    payload, files = parse_request_payload()
    original_post_id = payload.get("post_id")
    post_id = resolve_post_id(original_post_id)
    comment = normalize_comment(payload.get("comment"))
    parent_id = payload.get("parent_id")
    post_as_channel = str(payload.get("post_as_channel") or "").strip().lower() in {"1", "true", "yes", "on"}
    verified_user = validate_max_init_data(payload.get("init_data", ""))

    if not post_id:
        return jsonify({"error": "Не передан post_id"}), 400
    if not verified_user:
        return jsonify({"error": "Не удалось подтвердить пользователя MAX"}), 400
    try:
        media_path, media_type = save_uploaded_media(files.get("image")) if files else (None, None)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if not comment and not media_path:
        return jsonify({"error": "Комментарий пустой"}), 400

    post = get_post_info(post_id)
    if not post:
        post = ensure_post_record(post_id, source_post_id=original_post_id)
    if not post:
        return jsonify({"error": "Пост не найден"}), 404
    source_chat_id = str(post.get("source_chat_id") or "").strip()
    channel = get_channel_info(source_chat_id) if source_chat_id else None
    if channel and channel.get("is_blocked"):
        return jsonify({"error": "Канал заблокирован"}), 403
    author_type = "channel" if post_as_channel else "user"
    author_name = verified_user["username"]
    author_public_username = verified_user.get("public_username", "")
    author_avatar_url = verified_user.get("avatar_url", "")
    channel_chat_id = None
    if post_as_channel:
        if not source_chat_id or not user_can_moderate_comment(verified_user["user_id"], post_id):
            return jsonify({"error": "Писать от имени канала может только администратор"}), 403
        author_name = (channel or {}).get("title") or "Канал"
        author_public_username = ""
        author_avatar_url = (channel or {}).get("avatar_url", "")
        channel_chat_id = source_chat_id

    normalized_parent_id = int(parent_id) if str(parent_id or "").isdigit() else None
    created_at = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    parent_comment = None
    if normalized_parent_id:
        parent_comment = conn.execute(
            "SELECT id, user_id FROM comments WHERE id = ?",
            (normalized_parent_id,),
        ).fetchone()
    cursor.execute(
        """
        INSERT INTO comments (post_id, user_id, username, author_type, channel_chat_id, public_username, avatar_url, comment, image_path, media_path, media_type, parent_id, edited_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            post_id,
            verified_user["user_id"],
            author_name,
            author_type,
            channel_chat_id,
            author_public_username,
            author_avatar_url,
            comment,
            media_path,
            media_path,
            media_type,
            normalized_parent_id,
            None,
            created_at,
        ),
    )
    conn.commit()
    comment_id = cursor.lastrowid
    conn.close()
    upsert_user_settings(verified_user)
    sync_store_db("comment-create")
    update_store_archive("comment-create")
    create_backup("comment-create")
    refresh_post_button(post_id)
    if parent_comment and parent_comment["user_id"] != verified_user["user_id"]:
        target_settings = get_user_settings(parent_comment["user_id"])
        if target_settings.get("notifications_enabled"):
            send_reply_notification(parent_comment["user_id"], author_name, comment, post_id)
    send_channel_admin_notifications(post_id, verified_user["user_id"], author_name, comment)

    return jsonify({"status": "success", "comment": {"id": comment_id}})


@app.route("/api/comment/<int:comment_id>", methods=["PUT"])
def edit_comment(comment_id):
    payload = request.get_json(silent=True) or {}
    comment = normalize_comment(payload.get("comment"))
    verified_user = validate_max_init_data(payload.get("init_data", ""))
    if not verified_user:
        return jsonify({"error": "Не удалось подтвердить пользователя MAX"}), 400

    conn = get_db_connection()
    row = conn.execute(
        "SELECT id, COALESCE(media_path, image_path) AS media_path FROM comments WHERE id = ? AND user_id = ?",
        (comment_id, verified_user["user_id"]),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Комментарий не найден или нет прав"}), 404
    if not comment and not row["media_path"]:
        conn.close()
        return jsonify({"error": "Комментарий пустой"}), 400

    edited_at = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE comments SET comment = ?, edited_at = ? WHERE id = ?", (comment, edited_at, comment_id))
    conn.commit()
    conn.close()
    sync_store_db("comment-edit")
    update_store_archive("comment-edit")
    create_backup("comment-edit")
    return jsonify({"status": "success", "edited_at": edited_at})


@app.route("/api/comment/<int:comment_id>", methods=["DELETE"])
def delete_comment(comment_id):
    payload = request.get_json(silent=True) or {}
    verified_user = validate_max_init_data(payload.get("init_data", ""))
    user_id = (verified_user or {}).get("user_id") or (payload.get("user_id") or "").strip()[:128]
    if not user_id:
        return jsonify({"error": "Не передан user_id"}), 400

    conn = get_db_connection()
    row = conn.execute(
        "SELECT id, post_id, user_id, COALESCE(media_path, image_path) AS media_path FROM comments WHERE id = ?",
        (comment_id,),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Комментарий не найден"}), 404
    is_owner = row["user_id"] == user_id
    is_admin = user_can_moderate_comment(user_id, row["post_id"])
    if not is_owner and not is_admin:
        conn.close()
        return jsonify({"error": "Комментарий не найден или нет прав"}), 404

    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    conn.commit()
    conn.close()

    if row["media_path"]:
        file_path = os.path.join(UPLOAD_DIR, row["media_path"])
        if os.path.exists(file_path):
            os.remove(file_path)
    sync_store_db("comment-delete")
    update_store_archive("comment-delete")
    create_backup("comment-delete")
    refresh_post_button(row["post_id"])
    return jsonify({"status": "success"})


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/admin/export-store")
def export_store():
    if not require_sync_secret():
        return jsonify({"error": "forbidden"}), 403
    if not os.path.exists(STORE_ARCHIVE_PATH):
        update_store_archive("sync-export")
    if not os.path.exists(STORE_ARCHIVE_PATH):
        return jsonify({"error": "store archive not found"}), 404
    return send_file(STORE_ARCHIVE_PATH, mimetype="application/zip", as_attachment=True, download_name="comment_store.zip")


@app.route("/api/admin/import-store", methods=["POST"])
def import_store():
    if not require_sync_secret():
        return jsonify({"error": "forbidden"}), 403
    file = request.files.get("archive")
    if not file or not file.filename:
        return jsonify({"error": "archive is required"}), 400
    temp_path = STORE_ARCHIVE_PATH + ".upload"
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        file.save(temp_path)
        current_count = count_comments_in_db(DB_PATH)
        incoming_count = count_comments_in_archive(temp_path)
        if incoming_count == 0 and current_count > 0:
            return jsonify({"error": "incoming archive is empty", "db_comment_count": current_count}), 409
        try:
            with open(temp_path, "rb") as source_file:
                archive_bytes = source_file.read()
            with open(STORE_ARCHIVE_PATH, "wb") as target_file:
                target_file.write(archive_bytes)
        except OSError:
            os.replace(temp_path, STORE_ARCHIVE_PATH)
        if not import_store_archive(STORE_ARCHIVE_PATH):
            return jsonify({"error": "failed to import archive"}), 500
        return jsonify({"status": "success", "db_comment_count": count_comments_in_db(DB_PATH)})
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@app.route("/api/admin/chats")
def export_known_chats():
    if not require_sync_secret():
        return jsonify({"error": "forbidden"}), 403
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT DISTINCT source_chat_id
        FROM posts
        WHERE TRIM(COALESCE(source_chat_id, '')) <> ''
        ORDER BY source_chat_id
        """
    ).fetchall()
    conn.close()
    return jsonify({"chat_ids": [str(row["source_chat_id"]) for row in rows]})


@app.route("/api/admin/channels")
def admin_channels():
    if not require_sync_secret():
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"channels": list_channels()})


@app.route("/api/admin/stats")
def admin_stats():
    if not require_sync_secret():
        return jsonify({"error": "forbidden"}), 403
    chat_id = str(request.args.get("chat_id") or "").strip()
    period = normalize_stats_period(request.args.get("period"))
    return jsonify(get_channel_stats(chat_id=chat_id or None, period=period))


@app.route("/api/admin/post/<path:post_id>")
def admin_post_lookup(post_id):
    if not require_sync_secret():
        return jsonify({"error": "forbidden"}), 403
    resolved_post_id = resolve_post_id(post_id)
    post = get_post_info(resolved_post_id) if resolved_post_id else None
    if not post and resolved_post_id:
        conn = get_db_connection()
        row = conn.execute("SELECT COUNT(*) AS count FROM comments WHERE post_id = ?", (resolved_post_id,)).fetchone()
        conn.close()
        if row and int(row["count"] or 0) > 0:
            post = build_placeholder_post_info(resolved_post_id, source_post_id=post_id)
    return jsonify({"post": post})


@app.route("/api/admin/channels/<path:chat_id>/block", methods=["POST"])
def admin_block_channel(chat_id):
    if not require_sync_secret():
        return jsonify({"error": "forbidden"}), 403
    payload = request.get_json(silent=True) or {}
    is_blocked = bool(payload.get("blocked", True))
    channel_info = fetch_chat_info(chat_id) or {}
    upsert_channel(
        chat_id,
        title=channel_info.get("title", ""),
        avatar_url=channel_info.get("avatar_url", ""),
        is_blocked=1 if is_blocked else 0,
    )
    sync_store_db("channel-block")
    update_store_archive("channel-block")
    create_backup("channel-block")
    return jsonify({"status": "success", "channel": get_channel_info(chat_id)})


@app.route("/api/admin/channels/<path:chat_id>/delete", methods=["POST"])
def admin_delete_channel(chat_id):
    if not require_sync_secret():
        return jsonify({"error": "forbidden"}), 403
    set_channel_deleted(chat_id, True)
    sync_store_db("channel-delete")
    update_store_archive("channel-delete")
    create_backup("channel-delete")
    return jsonify({"status": "success", "channel": get_channel_info(chat_id)})


@app.route("/api/admin/channels/<path:chat_id>/restore", methods=["POST"])
def admin_restore_channel(chat_id):
    if not require_sync_secret():
        return jsonify({"error": "forbidden"}), 403
    payload = request.get_json(silent=True) or {}
    owner_user_id = str(payload.get("owner_user_id") or "").strip()[:128]
    owner_username = (payload.get("owner_username") or "").strip()[:255]
    channel_info = fetch_chat_info(chat_id) or {}
    upsert_channel(
        chat_id,
        title=channel_info.get("title", ""),
        avatar_url=channel_info.get("avatar_url", ""),
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        is_blocked=0,
        is_deleted=0,
    )
    sync_store_db("channel-restore")
    update_store_archive("channel-restore")
    create_backup("channel-restore")
    return jsonify({"status": "success", "channel": get_channel_info(chat_id)})


@app.route("/health")
def health():
    backups = []
    if os.path.isdir(BACKUP_DIR):
        for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
            if name.endswith(".zip"):
                backups.append(name)
            if len(backups) >= 5:
                break
    return jsonify(
        {
            "status": "ok",
            "data_dir": DATA_DIR,
            "db_exists": os.path.exists(DB_PATH),
            "db_comment_count": count_comments_in_db(DB_PATH),
            "store_db_exists": os.path.exists(STORE_DB_PATH),
            "store_db_path": STORE_DB_PATH,
            "store_db_comment_count": count_comments_in_db(STORE_DB_PATH),
            "store_archive_exists": os.path.exists(STORE_ARCHIVE_PATH),
            "store_archive_path": STORE_ARCHIVE_PATH,
            "backup_dir": BACKUP_DIR,
            "recent_backups": backups,
        }
    )


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "Файл слишком большой для загрузки"}), 413


migrate_legacy_storage()
restore_store_db_if_needed()
restore_store_archive_if_needed()
restore_latest_backup_if_needed()
init_db()
if count_comments_in_db(DB_PATH) > 0:
    sync_store_db("startup")
    update_store_archive("startup")
    create_backup("startup")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=os.getenv("APP_DEBUG", "").lower() == "true")
