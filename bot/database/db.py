import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path("data/books.db")

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

DEFAULT_CATEGORIES = [
    ("📚 ادبیات",), ("🧠 روان‌شناسی",), ("🏛 فلسفه",), ("📜 تاریخ",),
    ("🔬 علمی",), ("💻 فناوری و کامپیوتر",), ("💰 اقتصاد و کسب‌وکار",),
    ("🌍 جغرافیا و سفر",), ("🎭 هنر",), ("🕌 دین و عرفان",),
    ("📖 رمان و داستان",), ("🧒 کودک و نوجوان",), ("🎓 دانشگاهی و آموزشی",),
    ("📝 شعر",), ("🌐 زبان و آموزش زبان",),
]

def now():
    return datetime.now().isoformat(timespec="seconds")

def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            first_name TEXT,
            username TEXT,
            created_at TEXT NOT NULL,
            last_seen_at TEXT,
            is_blocked INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, author TEXT, category_id INTEGER, language TEXT,
            description TEXT, year INTEGER, format TEXT, file_id TEXT, file_name TEXT,
            submitted_by INTEGER, approved_by INTEGER, status TEXT NOT NULL DEFAULT 'pending',
            rejection_reason TEXT, views INTEGER DEFAULT 0, downloads INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, approved_at TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL, book_id INTEGER NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(user_id, book_id)
        );
        CREATE TABLE IF NOT EXISTS book_views (
            user_id INTEGER NOT NULL, book_id INTEGER NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(user_id, book_id)
        );
        CREATE TABLE IF NOT EXISTS book_downloads (
            user_id INTEGER NOT NULL, book_id INTEGER NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(user_id, book_id)
        );
        CREATE TABLE IF NOT EXISTS bot_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_activity_user ON bot_activity(user_id);
        CREATE INDEX IF NOT EXISTS idx_activity_action ON bot_activity(action);
        CREATE INDEX IF NOT EXISTS idx_activity_date ON bot_activity(created_at);
        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id INTEGER PRIMARY KEY,
            flow TEXT NOT NULL,
            state TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER,
            direction TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_start INTEGER DEFAULT 0,
            UNIQUE(chat_id, message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at);
        CREATE TABLE IF NOT EXISTS panels (
            chat_id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL,
            opened_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """)
        # Safe migrations for databases created by earlier versions.
        for sql in [
            "ALTER TABLE users ADD COLUMN last_seen_at TEXT",
            "ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        conn.executemany("INSERT OR IGNORE INTO categories(name) VALUES (?)", DEFAULT_CATEGORIES)

def record_activity(user_id, action):
    with get_conn() as conn:
        conn.execute("INSERT INTO bot_activity(user_id, action, created_at) VALUES (?, ?, ?)", (user_id, action, now()))

def upsert_user(user):
    stamp = now()
    with get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE telegram_id=?", (user.id,)).fetchone()
        conn.execute("""
            INSERT INTO users(telegram_id, first_name, username, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                first_name=excluded.first_name, username=excluded.username,
                last_seen_at=excluded.last_seen_at
        """, (user.id, user.first_name or "", user.username or "", stamp, stamp))
    if not exists:
        record_activity(user.id, "new_user")
    else:
        record_activity(user.id, "start")

def add_book(data):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO books(title, author, category_id, language, description, year, format,
                file_id, file_name, submitted_by, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (data["title"], data["author"], data.get("category_id"), data.get("language"),
              data.get("description"), data.get("year"), data.get("format"), data["file_id"],
              data.get("file_name"), data["submitted_by"], now()))
        return cur.lastrowid

def book_exists(title, author, file_name=None):
    title = (title or "").strip()
    author = (author or "").strip()
    with get_conn() as conn:
        if file_name:
            row = conn.execute("SELECT 1 FROM books WHERE file_name=? LIMIT 1", (file_name,)).fetchone()
            if row:
                return True
        row = conn.execute("SELECT 1 FROM books WHERE title=? AND COALESCE(author, '')=? LIMIT 1", (title, author)).fetchone()
        return row is not None

def publish_book(book_id, owner_id):
    with get_conn() as conn:
        conn.execute("UPDATE books SET status='published', approved_by=?, approved_at=? WHERE id=? AND status='pending'",
                     (owner_id, now(), book_id))

def reject_book(book_id, reason=""):
    with get_conn() as conn:
        conn.execute("UPDATE books SET status='rejected', rejection_reason=? WHERE id=? AND status='pending'", (reason, book_id))

def get_book(book_id):
    with get_conn() as conn:
        return conn.execute("""SELECT b.*, c.name AS category_name FROM books b
            LEFT JOIN categories c ON c.id=b.category_id WHERE b.id=?""", (book_id,)).fetchone()

def categories():
    with get_conn() as conn:
        return conn.execute("SELECT id, name FROM categories ORDER BY id").fetchall()

def get_category(category_id):
    with get_conn() as conn:
        return conn.execute("SELECT id, name FROM categories WHERE id=?", (category_id,)).fetchone()

def category_books(category_id, query=""):
    with get_conn() as conn:
        q = f"%{query.strip()}%"
        return conn.execute("""SELECT b.*, c.name AS category_name FROM books b
            LEFT JOIN categories c ON c.id=b.category_id
            WHERE b.status='published' AND b.category_id=? AND
            (?='' OR b.title LIKE ? OR COALESCE(b.author,'') LIKE ? OR COALESCE(b.description,'') LIKE ?)
            ORDER BY b.created_at DESC""", (category_id, query.strip(), q, q, q)).fetchall()

def category_count(category_id):
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM books WHERE status='published' AND category_id=?", (category_id,)).fetchone()[0]

def popular_books(limit=100):
    with get_conn() as conn:
        return conn.execute("""SELECT b.*, c.name AS category_name,
            (COALESCE(b.downloads,0)*3+COALESCE(b.views,0)) AS popularity_score
            FROM books b LEFT JOIN categories c ON c.id=b.category_id
            WHERE b.status='published' ORDER BY popularity_score DESC, b.created_at DESC LIMIT ?""", (limit,)).fetchall()

def latest_books(limit=100):
    with get_conn() as conn:
        return conn.execute("""SELECT b.*, c.name AS category_name FROM books b
            LEFT JOIN categories c ON c.id=b.category_id WHERE b.status='published'
            ORDER BY b.created_at DESC LIMIT ?""", (limit,)).fetchall()

def increment_view(book_id, user_id):
    with get_conn() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO book_views(user_id,book_id,created_at) VALUES (?,?,?)", (user_id, book_id, now()))
        if cur.rowcount == 1:
            conn.execute("UPDATE books SET views=COALESCE(views,0)+1 WHERE id=? AND status='published'", (book_id,))
            conn.execute("INSERT INTO bot_activity(user_id,action,created_at) VALUES (?,?,?)", (user_id,"view_book",now()))
            return True
    return False

def increment_download(book_id, user_id):
    with get_conn() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO book_downloads(user_id,book_id,created_at) VALUES (?,?,?)", (user_id, book_id, now()))
        if cur.rowcount == 1:
            conn.execute("UPDATE books SET downloads=COALESCE(downloads,0)+1 WHERE id=? AND status='published'", (book_id,))
            conn.execute("INSERT INTO bot_activity(user_id,action,created_at) VALUES (?,?,?)", (user_id,"download_book",now()))
            return True
    return False

def published_books(query=""):
    with get_conn() as conn:
        q=f"%{query.strip()}%"
        return conn.execute("""SELECT b.*, c.name AS category_name FROM books b LEFT JOIN categories c ON c.id=b.category_id
            WHERE b.status='published' AND (?='' OR b.title LIKE ? OR COALESCE(b.author,'') LIKE ? OR COALESCE(b.description,'') LIKE ?)
            ORDER BY b.created_at DESC""", (query.strip(),q,q,q)).fetchall()

def pending_books():
    with get_conn() as conn:
        return conn.execute("""SELECT b.*, u.first_name, u.username FROM books b LEFT JOIN users u ON u.telegram_id=b.submitted_by
            WHERE b.status='pending' ORDER BY b.created_at ASC""").fetchall()

def published_count():
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM books WHERE status='published'").fetchone()[0]
def pending_count():
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM books WHERE status='pending'").fetchone()[0]

def rejected_count():
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM books WHERE status='rejected'").fetchone()[0]
def total_books():
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
def total_users():
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
def blocked_users():
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM users WHERE is_blocked=1").fetchone()[0]
def active_users(days=30):
    since=(datetime.now()-timedelta(days=days)).isoformat(timespec="seconds")
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM users WHERE last_seen_at>=?",(since,)).fetchone()[0]
def new_users(period):
    if period=="today": since=datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
    elif period=="week": since=datetime.now()-timedelta(days=7)
    else: since=datetime.now()-timedelta(days=30)
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM users WHERE created_at>=?",(since.isoformat(timespec="seconds"),)).fetchone()[0]
def activity_count(action=None, days=None):
    params=[]; where=[]
    if action: where.append("action=?"); params.append(action)
    if days is not None: where.append("created_at>=?"); params.append((datetime.now()-timedelta(days=days)).isoformat(timespec="seconds"))
    sql="SELECT COUNT(*) FROM bot_activity" + (" WHERE "+" AND ".join(where) if where else "")
    with get_conn() as conn: return conn.execute(sql,params).fetchone()[0]
def all_views():
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM book_views").fetchone()[0]
def all_downloads():
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM book_downloads").fetchone()[0]
def all_favorites():
    with get_conn() as conn: return conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]

def admin_stats():
    return {
        "users": total_users(), "active_30": active_users(30), "new_today": new_users("today"),
        "new_week": new_users("week"), "new_month": new_users("month"), "blocked": blocked_users(),
        "books": total_books(), "published": published_count(), "pending": pending_count(), "rejected": rejected_count(),
        "views": all_views(), "downloads": all_downloads(), "favorites": all_favorites(),
        "searches": activity_count("search", None), "activity": activity_count(),
    }

def find_users(query="", limit=30):
    q=f"%{query.strip()}%"
    with get_conn() as conn:
        return conn.execute("""SELECT * FROM users WHERE (?='' OR CAST(telegram_id AS TEXT) LIKE ? OR COALESCE(first_name,'') LIKE ? OR COALESCE(username,'') LIKE ?)
            ORDER BY last_seen_at DESC LIMIT ?""", (query.strip(),q,q,q,limit)).fetchall()
def get_user(telegram_id):
    with get_conn() as conn: return conn.execute("SELECT * FROM users WHERE telegram_id=?",(telegram_id,)).fetchone()
def user_activity_count(telegram_id, action=None):
    with get_conn() as conn:
        if action: return conn.execute("SELECT COUNT(*) FROM bot_activity WHERE user_id=? AND action=?",(telegram_id,action)).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM bot_activity WHERE user_id=?",(telegram_id,)).fetchone()[0]
def set_user_blocked(telegram_id, blocked):
    with get_conn() as conn: conn.execute("UPDATE users SET is_blocked=? WHERE telegram_id=?",(1 if blocked else 0,telegram_id))

def all_published_books(limit=100):
    with get_conn() as conn: return conn.execute("SELECT * FROM books WHERE status='published' ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
def all_user_books(limit=100):
    with get_conn() as conn: return conn.execute("""SELECT b.*,u.first_name,u.username FROM books b LEFT JOIN users u ON u.telegram_id=b.submitted_by
        WHERE b.submitted_by IS NOT NULL ORDER BY b.created_at DESC LIMIT ?""",(limit,)).fetchall()
def update_book(book_id, title=None, author=None, category_id=None, description=None):
    with get_conn() as conn:
        conn.execute("""UPDATE books SET title=COALESCE(?,title), author=COALESCE(?,author), category_id=COALESCE(?,category_id), description=COALESCE(?,description) WHERE id=?""",
                     (title,author,category_id,description,book_id))
def delete_book(book_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM favorites WHERE book_id=?",(book_id,))
        conn.execute("DELETE FROM book_views WHERE book_id=?",(book_id,))
        conn.execute("DELETE FROM book_downloads WHERE book_id=?",(book_id,))
        conn.execute("DELETE FROM books WHERE id=?",(book_id,))
def add_category(name):
    with get_conn() as conn:
        cur=conn.execute("INSERT INTO categories(name) VALUES (?)",(name.strip(),)); return cur.lastrowid
def rename_category(category_id,name):
    with get_conn() as conn: conn.execute("UPDATE categories SET name=? WHERE id=?",(name.strip(),category_id))
def delete_category(category_id):
    with get_conn() as conn:
        count=conn.execute("SELECT COUNT(*) FROM books WHERE category_id=?",(category_id,)).fetchone()[0]
        if count: return False
        conn.execute("DELETE FROM categories WHERE id=?",(category_id,)); return True

def user_submissions(user_id):
    with get_conn() as conn: return conn.execute("SELECT * FROM books WHERE submitted_by=? AND status!='rejected' ORDER BY created_at DESC",(user_id,)).fetchall()
def downloaded_books(user_id,limit=100):
    with get_conn() as conn: return conn.execute("""SELECT b.*,c.name AS category_name,d.created_at AS activity_at FROM book_downloads d JOIN books b ON b.id=d.book_id LEFT JOIN categories c ON c.id=b.category_id WHERE d.user_id=? AND b.status='published' ORDER BY d.created_at DESC LIMIT ?""",(user_id,limit)).fetchall()
def recently_viewed_books(user_id,limit=100):
    with get_conn() as conn: return conn.execute("""SELECT b.*,c.name AS category_name,v.created_at AS activity_at FROM book_views v JOIN books b ON b.id=v.book_id LEFT JOIN categories c ON c.id=b.category_id WHERE v.user_id=? AND b.status='published' ORDER BY v.created_at DESC LIMIT ?""",(user_id,limit)).fetchall()
def favorite_books(user_id,limit=100):
    with get_conn() as conn: return conn.execute("""SELECT b.*,c.name AS category_name,f.created_at AS activity_at FROM favorites f JOIN books b ON b.id=f.book_id LEFT JOIN categories c ON c.id=b.category_id WHERE f.user_id=? AND b.status='published' ORDER BY f.created_at DESC LIMIT ?""",(user_id,limit)).fetchall()
def is_favorite(user_id,book_id):
    with get_conn() as conn: return conn.execute("SELECT 1 FROM favorites WHERE user_id=? AND book_id=?",(user_id,book_id)).fetchone() is not None
def toggle_favorite(user_id,book_id):
    with get_conn() as conn:
        exists=conn.execute("SELECT 1 FROM favorites WHERE user_id=? AND book_id=?",(user_id,book_id)).fetchone()
        if exists:
            conn.execute("DELETE FROM favorites WHERE user_id=? AND book_id=?",(user_id,book_id)); return False
        conn.execute("INSERT INTO favorites(user_id,book_id,created_at) VALUES (?,?,?)",(user_id,book_id,now())); return True


def set_session(user_id, flow, state, data=None):
    with get_conn() as conn:
        conn.execute("""INSERT INTO user_sessions(user_id,flow,state,data,updated_at) VALUES (?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET flow=excluded.flow,state=excluded.state,data=excluded.data,updated_at=excluded.updated_at""",
                     (user_id, flow, str(state), json.dumps(data or {}, ensure_ascii=False), now()))

def get_session(user_id):
    with get_conn() as conn:
        row=conn.execute("SELECT * FROM user_sessions WHERE user_id=?",(user_id,)).fetchone()
    if not row: return None
    try: data=json.loads(row["data"] or "{}")
    except Exception: data={}
    return {"flow":row["flow"],"state":row["state"],"data":data,"updated_at":row["updated_at"]}

def clear_session(user_id):
    with get_conn() as conn: conn.execute("DELETE FROM user_sessions WHERE user_id=?",(user_id,))

def log_chat_message(chat_id, message_id, user_id, direction, is_start=False, created_at=None):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO chat_messages(chat_id,message_id,user_id,direction,created_at,is_start) VALUES (?,?,?,?,?,?)",
                     (chat_id,message_id,user_id,direction,created_at or now(),1 if is_start else 0))

def get_expired_messages(cutoff):
    with get_conn() as conn:
        return conn.execute("SELECT id,chat_id,message_id FROM chat_messages WHERE created_at<=? AND is_start=0 ORDER BY id LIMIT 500",(cutoff,)).fetchall()

def remove_logged_message(row_id):
    with get_conn() as conn: conn.execute("DELETE FROM chat_messages WHERE id=?",(row_id,))

def remove_logged_messages_before(cutoff):
    with get_conn() as conn: conn.execute("DELETE FROM chat_messages WHERE created_at<=? AND is_start=0",(cutoff,))

def set_panel(chat_id, message_id, opened_at, expires_at):
    with get_conn() as conn:
        conn.execute("""INSERT INTO panels(chat_id,message_id,opened_at,expires_at) VALUES (?,?,?,?)
            ON CONFLICT(chat_id) DO UPDATE SET message_id=excluded.message_id,opened_at=excluded.opened_at,expires_at=excluded.expires_at""",(chat_id,message_id,opened_at,expires_at))

def get_panel(chat_id):
    with get_conn() as conn: return conn.execute("SELECT chat_id,message_id FROM panels WHERE chat_id=?",(chat_id,)).fetchone()

def get_expired_panels(at_time):
    with get_conn() as conn: return conn.execute("SELECT chat_id,message_id FROM panels WHERE expires_at<=?",(at_time,)).fetchall()

def clear_panel(chat_id, message_id=None):
    with get_conn() as conn:
        if message_id is None: conn.execute("DELETE FROM panels WHERE chat_id=?",(chat_id,))
        else: conn.execute("DELETE FROM panels WHERE chat_id=? AND message_id=?",(chat_id,message_id))
