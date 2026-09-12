import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ConversationHandler, MessageHandler, ContextTypes, filters
)

from config import BOT_TOKEN, OWNER_ID, CHANNEL_USERNAME, GROUP_CHAT_ID
from bot.database.db import (
    init_db, upsert_user, published_books, popular_books, latest_books, get_book,
    get_session, set_session, clear_session, log_chat_message, set_panel, get_panel, clear_panel,
    downloaded_books, recently_viewed_books, favorite_books,
    toggle_favorite, is_favorite, increment_view, increment_download
)
from bot.keyboards.main import force_join_keyboard, main_keyboard
from bot.handlers.bulk_import import (
    bulk_import_start, bulk_receive_zip, bulk_csv_template, bulk_cancel, BULK_ZIP
)
from bot.handlers.add_book import (
    start_add_book, get_title, get_author, get_category, get_description,
    get_file, cancel_add_book, select_category, description_none, TITLE, AUTHOR, CATEGORY, DESCRIPTION, FILE
)
from bot.handlers.categories import show_categories, show_category, category_page, category_search_start, category_search_cancel, receive_category_search
from bot.handlers.admin import (
    admin_panel, book_management, pending_list, approve, reject,
    admin_view, simple_admin_info, admin_stats, admin_users, admin_user, user_block, admin_categories, admin_cat, admin_cat_delete, confirm_delete, delete, admin_broadcast_info, start_edit_book, edit_book_id, edit_book_title, edit_book_author, edit_book_finish, start_cat_add, start_cat_rename, finish_cat_name, EDIT_ID, EDIT_TITLE, EDIT_AUTHOR, EDIT_DESCRIPTION, CAT_NAME
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/healthz"):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health server listening on port %s", port)
    return server

from bot.services.maintenance import cleanup_job, close_expired_panels_job

FORCE_JOIN_TEXT = """<b>عضویت اجباری 🔐</b>

<b>برای فعال شدن دسترسی شما به ربات عضویت در کانال و گروه زیر الزامی است.</b>
━━━━━━━━━━━━━━━━
<b>پس از عضویت، روی «✅ بررسی عضویت» بزنید.</b>"""

MAIN_PANEL_TEXT = """<b>📚 به کتابخانه زمهریر خوش آمدید</b>

<b>اینجا می‌توانید در میان مجموعه کتاب های موجود
جستجو کنید ، کتاب ها را بر اساس دسته‌ بندی پیدا کنید
و کتاب‌های موردعلاقه‌تان را ذخیره کنید.</b>

━━━━━━━━━━━━━━━━
<b>از منوی زیر انتخاب کنید:</b>"""

async def membership(bot, user_id):
    channel_ok = False
    group_ok = False
    try:
        m = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        channel_ok = m.status in {"member", "administrator", "creator"}
    except Exception:
        pass
    try:
        m = await bot.get_chat_member(GROUP_CHAT_ID, user_id)
        group_ok = m.status in {"member", "administrator", "creator"}
    except Exception:
        pass
    return channel_ok, group_ok

async def show_main(update, context):
    user = update.effective_user
    if not user:
        return
    upsert_user(user)
    text = MAIN_PANEL_TEXT
    markup = main_keyboard(user.id == OWNER_ID)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        stamp = datetime.now()
        set_panel(update.callback_query.message.chat_id, update.callback_query.message.message_id, stamp.isoformat(timespec="seconds"), (stamp + timedelta(minutes=10)).isoformat(timespec="seconds"))
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    upsert_user(user)
    old_panel = get_panel(user.id)
    if old_panel:
        try:
            await context.bot.delete_message(chat_id=user.id, message_id=old_panel["message_id"])
        except Exception:
            pass
        clear_panel(user.id, old_panel["message_id"])
    c, g = await membership(context.bot, user.id)
    if c and g:
        msg = await update.message.reply_text(MAIN_PANEL_TEXT, reply_markup=main_keyboard(user.id == OWNER_ID), parse_mode="HTML")
        stamp = datetime.now()
        set_panel(user.id, msg.message_id, stamp.isoformat(timespec="seconds"), (stamp + timedelta(minutes=10)).isoformat(timespec="seconds"))
    else:
        await update.message.reply_text(FORCE_JOIN_TEXT, reply_markup=force_join_keyboard(c, g), parse_mode="HTML")

async def check_membership(update, context):
    q = update.callback_query
    await q.answer()
    c, g = await membership(context.bot, q.from_user.id)
    if c and g:
        await q.edit_message_text(MAIN_PANEL_TEXT, reply_markup=main_keyboard(q.from_user.id == OWNER_ID), parse_mode="HTML")
        stamp = datetime.now()
        set_panel(q.message.chat_id, q.message.message_id, stamp.isoformat(timespec="seconds"), (stamp + timedelta(minutes=10)).isoformat(timespec="seconds"))
    else:
        await q.edit_message_reply_markup(reply_markup=force_join_keyboard(c, g))

async def search_start(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["searching"] = True
    set_session(q.from_user.id, "search", "searching", {})
    await q.edit_message_text(
        "<b>🔎 جستجوی کتاب</b>\n\n"
        "<b>نام کتاب، نویسنده یا بخشی از عنوان کتاب را برای جستجو ارسال کنید.</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "<blockquote><b>مثال:</b>\nچنین گفت زرتشت\nفردریش نیچه\nصد سال تنهایی</blockquote>",
        reply_markup=__import__("telegram").InlineKeyboardMarkup(
            [[__import__("telegram").InlineKeyboardButton("❌ لغو جستجو", callback_data="search_cancel")]]
        ),
        parse_mode="HTML"
    )

async def search_cancel(update, context):
    context.user_data.pop("searching", None)
    clear_session(update.callback_query.from_user.id)
    await show_main(update, context)

async def receive_search(update, context):
    if await receive_category_search(update, context):
        return
    if not context.user_data.get("searching"):
        return
    query = update.message.text.strip()
    from bot.database.db import record_activity
    record_activity(update.effective_user.id, "search")
    rows = published_books(query)
    context.user_data["searching"] = False
    clear_session(update.effective_user.id)
    if not rows:
        await update.message.reply_text(
            "<b>🔎 نتیجه جستجو</b>\n\n━━━━━━━━━━━━━━━━\n"
            "❌ کتابی با این مشخصات پیدا نشد.",
            reply_markup=main_keyboard(update.effective_user.id == OWNER_ID),
            parse_mode="HTML"
        )
        return
    buttons = []
    for b in rows[:30]:
        author = b["author"] or "نامشخص"
        buttons.append([__import__("telegram").InlineKeyboardButton(
            f"📖 {b['title']} — {author}", callback_data=f"book:{b['id']}"
        )])
    buttons.append([__import__("telegram").InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
    await update.message.reply_text(
        f"<b>🔎 نتایج جستجو</b>\n\n━━━━━━━━━━━━━━━━\n<b>{len(rows)}</b> نتیجه پیدا شد.",
        reply_markup=__import__("telegram").InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )

async def new_books(update, context):
    q = update.callback_query
    await q.answer()
    rows = latest_books(100)
    context.user_data["new_books_page"] = 0
    await render_new_books(q, rows, 0)

async def render_new_books(q, rows, page):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    PAGE_SIZE = 6
    total_pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_rows = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = ["<b>🆕 تازه‌اضافه‌شده‌ها</b>", "", "━━━━━━━━━━━━━━━━",
             "<b>جدیدترین کتاب‌های منتشرشده</b>", ""]
    if not page_rows:
        lines.append("❌ هنوز کتابی برای نمایش وجود ندارد.")
    else:
        for i, b in enumerate(page_rows):
            lines.append(f"📖 <b>{escape(b['title'] or 'بدون عنوان')}</b>")
            lines.append(f"✍️ {escape(b['author'] or 'نامشخص')}")
            lines.append(f"🗂 {escape(b['category_name'] or 'نامشخص')}")
            if i != len(page_rows) - 1:
                lines.append("")

    lines += ["", "━━━━━━━━━━━━━━━━", f"<b>📄 صفحه {page + 1} از {total_pages}</b>"]
    buttons = []
    for b in page_rows:
        buttons.append([InlineKeyboardButton(
            f"📖 {b['title']}", callback_data=f"book:{b['id']}:new"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"new_books_page:{page-1}"))
    nav.append(InlineKeyboardButton(f"صفحه {page+1} از {total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("➡️ صفحه بعد", callback_data=f"new_books_page:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔎 جستجو در تازه‌اضافه‌شده‌ها", callback_data="new_books_search")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def new_books_page(update, context):
    q = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1])
    await render_new_books(q, latest_books(100), page)

async def my_library(update, context):
    q = update.callback_query
    await q.answer()
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    text = (
        "<b>📚 کتابخانه من</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "<b>کتاب‌های شخصی شما را از اینجا مدیریت کنید.</b>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 دانلودشده‌ها", callback_data="my_downloads")],
        [InlineKeyboardButton("🕘 اخیراً مشاهده‌شده‌ها", callback_data="my_recent")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ])
    await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

async def favorite_books_view(update, context):
    q = update.callback_query
    await q.answer()
    await render_user_books(q, favorite_books(q.from_user.id, 100), 0, "favorites")

async def my_downloads(update, context):
    q = update.callback_query
    await q.answer()
    await render_user_books(q, downloaded_books(q.from_user.id, 100), 0, "downloads")

async def my_recent(update, context):
    q = update.callback_query
    await q.answer()
    await render_user_books(q, recently_viewed_books(q.from_user.id, 100), 0, "recent")

async def render_user_books(q, rows, page, source):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    PAGE_SIZE = 6
    total_pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_rows = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    titles = {
        "favorites": "⭐ علاقه‌مندی‌ها",
        "downloads": "📥 دانلودشده‌ها",
        "recent": "🕘 اخیراً مشاهده‌شده‌ها",
    }
    descriptions = {
        "favorites": "کتاب‌هایی که به علاقه‌مندی‌های خود اضافه کرده‌اید.",
        "downloads": "کتاب‌هایی که قبلاً دریافت کرده‌اید.",
        "recent": "آخرین کتاب‌هایی که مشاهده کرده‌اید.",
    }
    empty = {
        "favorites": "❌ هنوز کتابی به علاقه‌مندی‌ها اضافه نکرده‌اید.",
        "downloads": "❌ هنوز کتابی دانلود نکرده‌اید.",
        "recent": "❌ هنوز کتابی مشاهده نکرده‌اید.",
    }

    lines = [f"<b>{titles[source]}</b>", "", "━━━━━━━━━━━━━━━━", f"<b>{descriptions[source]}</b>", ""]
    if not page_rows:
        lines.append(empty[source])
    else:
        for i, b in enumerate(page_rows):
            lines.append(f"📖 <b>{escape(b['title'] or 'بدون عنوان')}</b>")
            lines.append(f"✍️ {escape(b['author'] or 'نامشخص')}")
            lines.append(f"🗂 {escape(b['category_name'] or 'نامشخص')}")
            if i != len(page_rows) - 1:
                lines.append("")

    lines += ["", "━━━━━━━━━━━━━━━━", f"<b>📄 صفحه {page + 1} از {total_pages}</b>"]
    buttons = []
    for b in page_rows:
        buttons.append([InlineKeyboardButton(
            f"📖 {b['title']}", callback_data=f"book:{b['id']}:{source}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"user_books_page:{source}:{page-1}"))
    nav.append(InlineKeyboardButton(f"صفحه {page+1} از {total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("➡️ صفحه بعد", callback_data=f"user_books_page:{source}:{page+1}"))
    if nav:
        buttons.append(nav)
    back = "my_library" if source != "favorites" else "main_menu"
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back)])
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def user_books_page(update, context):
    q = update.callback_query
    await q.answer()
    _, source, page = q.data.split(":")
    uid = q.from_user.id
    loaders = {
        "favorites": favorite_books,
        "downloads": downloaded_books,
        "recent": recently_viewed_books,
    }
    rows = loaders[source](uid, 100)
    await render_user_books(q, rows, int(page), source)

async def popular(update, context):
    q = update.callback_query
    await q.answer()
    rows = popular_books(100)
    context.user_data["popular_page"] = 0
    await render_popular(q, rows, 0)

async def render_popular(q, rows, page):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    PAGE_SIZE = 6
    total_pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_rows = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = ["<b>🔥 محبوب‌ترین کتاب‌ها</b>", "", "━━━━━━━━━━━━━━━━",
             "<b>بر اساس بیشترین دانلود و بازدید</b>", ""]
    if not page_rows:
        lines.append("❌ هنوز کتابی برای نمایش وجود ندارد.")
    else:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣"]
        for i, b in enumerate(page_rows):
            rank = page * PAGE_SIZE + i
            medal = medals[i]
            lines.append(f"{medal} <b>{b['title']}</b>")
            lines.append(f"👤 {b['author'] or 'نامشخص'}")
            lines.append(f"👁 بازدید: {b['views'] or 0}    ⬇️ دانلود: {b['downloads'] or 0}")
            if i != len(page_rows) - 1:
                lines.append("")

    lines += ["", "━━━━━━━━━━━━━━━━", f"<b>📄 صفحه {page + 1} از {total_pages}</b>"]
    buttons = []
    for b in page_rows:
        buttons.append([InlineKeyboardButton(f"📖 {b['title']}", callback_data=f"book:{b['id']}:popular")])
    nav=[]
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"popular_page:{page-1}"))
    nav.append(InlineKeyboardButton(f"صفحه {page+1} از {total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("➡️ صفحه بعد", callback_data=f"popular_page:{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔎 جستجو در محبوب‌ترین‌ها", callback_data="popular_search")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def popular_page(update, context):
    q = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1])
    await render_popular(q, popular_books(100), page)

async def show_book(update, context):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    book_id = int(parts[1])
    source = parts[2] if len(parts) > 2 else "search"
    b = get_book(book_id)
    if not b or b["status"] != "published":
        await q.answer("این کتاب در دسترس نیست.", show_alert=True)
        return

    increment_view(book_id, q.from_user.id)
    b = get_book(book_id)
    fav = is_favorite(q.from_user.id, book_id)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 دریافت کتاب", callback_data=f"download:{book_id}")],
        [InlineKeyboardButton("⭐ حذف از علاقه‌مندی‌ها" if fav else "⭐ افزودن به علاقه‌مندی‌ها", callback_data=f"favorite:{book_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=(
            "popular" if source == "popular" else
            "new_books" if source == "new" else
            "my_library" if source in {"downloads", "recent"} else
            "favorites" if source == "favorites" else
            "search_books"
        ))],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ])
    title = escape(b["title"] or "بدون عنوان")
    author = escape(b["author"] or "نامشخص")
    category_name = escape(b["category_name"] or "نامشخص")
    description = escape(b["description"] or "ندارد")
    language = escape(b["language"] or "نامشخص")
    file_name = escape(b["file_name"] or "موجود")
    fmt = escape(b["format"] or "نامشخص")
    year = escape(str(b["year"])) if b["year"] else "نامشخص"
    text = (
        f"<b>📖 {title}</b>\n\n"
        f"✍️ <b>نویسنده:</b> {author}\n"
        f"🗂 <b>دسته‌بندی:</b> {category_name}\n"
        f"🌐 <b>زبان:</b> {language}\n"
        f"📅 <b>سال انتشار:</b> {year}\n"
        f"📄 <b>فرمت:</b> {fmt}\n"
        f"📝 <b>توضیحات:</b> {description}\n\n"
        f"👁 <b>بازدید:</b> {b['views'] or 0}    ⬇️ <b>دانلود:</b> {b['downloads'] or 0}\n"
        f"📎 <b>فایل:</b> {file_name}\n\n"
        f"━━━━━━━━━━━━━━━━"
    )
    await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

async def favorite(update, context):
    q = update.callback_query
    await q.answer()
    book_id = int(q.data.split(":")[1])
    state = toggle_favorite(q.from_user.id, book_id)
    await show_book(update, context)
    await q.answer("⭐ به علاقه‌مندی‌ها اضافه شد." if state else "از علاقه‌مندی‌ها حذف شد.")

async def download(update, context):
    q = update.callback_query
    await q.answer()
    book_id = int(q.data.split(":")[1])
    b = get_book(book_id)
    if not b or not b["file_id"]:
        await q.answer("فایل این کتاب موجود نیست.", show_alert=True)
        return
    try:
        await context.bot.send_document(
            chat_id=q.from_user.id,
            document=b["file_id"],
            caption=f"📖 {b['title']}\n✍️ {b['author'] or 'نامشخص'}"
        )
        increment_download(book_id, q.from_user.id)
        await q.answer("📥 فایل ارسال شد.")
    except Exception:
        await q.answer("ارسال فایل انجام نشد.", show_alert=True)

async def help_page(update, context):
    q = update.callback_query
    await q.answer()
    text = """<b>📖 راهنمای کتابخانه زمهریر</b>

━━━━━━━━━━━━━━━━

🔎 <b>جستجوی کتاب</b>
با جستجو بر اساس نام کتاب یا نویسنده، کتاب موردنظر خود را پیدا کنید.

🗂 <b>دسته‌بندی کتاب‌ها</b>
کتاب‌ها بر اساس موضوع دسته‌بندی شده‌اند تا پیدا کردن کتاب مناسب راحت‌تر باشد.

🔥 <b>محبوب‌ترین‌ها</b>
کتاب‌هایی که بیشترین بازدید و دانلود را داشته‌اند در این بخش نمایش داده می‌شوند.

🆕 <b>تازه‌اضافه‌شده‌ها</b>
آخرین کتاب‌های منتشرشده در کتابخانه.

📚 <b>کتابخانه من</b>
کتاب‌های دانلودشده و کتاب‌هایی که اخیراً مشاهده کرده‌اید در این بخش قرار می‌گیرند.

⭐ <b>علاقه‌مندی‌ها</b>
کتاب‌های موردعلاقه خود را ذخیره کنید تا بعداً سریع به آن‌ها دسترسی داشته باشید.

━━━━━━━━━━━━━━━━

📤 <b>ارسال کتاب</b>
شما هم می‌توانید کتابی را برای اضافه شدن به کتابخانه ارسال کنید. کتاب‌های ارسالی کاربران ابتدا بررسی شده و پس از تأیید در کتابخانه منتشر می‌شوند.

━━━━━━━━━━━━━━━━

💡 <b>نکته:</b>
برای مشاهده جزئیات هر کتاب، روی نام آن بزنید."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]), parse_mode="HTML")

async def placeholder(update, context):
    q = update.callback_query
    await q.answer("این بخش در نسخه بعدی فعال می‌شود.", show_alert=True)

async def close_panel(update, context):
    q = update.callback_query
    await q.answer("پنل بسته شد.")
    if q.message:
        try:
            await q.message.delete()
        except Exception:
            pass
        clear_panel(q.message.chat_id, q.message.message_id)

async def log_incoming(update, context):
    m = update.message
    u = update.effective_user
    if m and u and not (m.text or "").strip().startswith("/start"):
        log_chat_message(m.chat_id, m.message_id, u.id, "in", False)

def install_message_logging(app):
    # PTB 22+ ExtBot methods are immutable; do not monkey-patch send_message/send_document.
    # Message cleanup/tracking is handled by the bot's explicit tracking logic.
    return

async def persistent_router(update, context):
    u = update.effective_user
    if not u:
        return
    if update.message and (update.message.text or "").strip().startswith("/"):
        return
    s = get_session(u.id)
    if not s:
        return
    flow, state, data = s["flow"], s["state"], s["data"]
    context.user_data["book_submission"] = data if flow == "add_book" else context.user_data.get("book_submission", {})
    if flow == "add_book":
        if update.callback_query and state == str(CATEGORY) and update.callback_query.data.startswith("submit_category:"):
            await select_category(update, context); return
        if update.callback_query and state == str(DESCRIPTION) and update.callback_query.data == "description_none":
            await description_none(update, context); return
        if update.callback_query and update.callback_query.data == "add_cancel":
            await cancel_add_book(update, context); return
        if update.message:
            if state == str(TITLE): await get_title(update, context); return
            if state == str(AUTHOR): await get_author(update, context); return
            if state == str(DESCRIPTION) and update.message.text: await get_description(update, context); return
            if state == str(FILE) and update.message.document: await get_file(update, context); return
    elif flow == "admin_edit":
        context.user_data["admin_edit"] = data
        if update.message:
            if state == str(EDIT_ID): await edit_book_id(update, context); return
            if state == str(EDIT_TITLE): await edit_book_title(update, context); return
            if state == str(EDIT_AUTHOR): await edit_book_author(update, context); return
            if state == str(EDIT_DESCRIPTION): await edit_book_finish(update, context); return
    elif flow == "admin_cat":
        context.user_data["admin_cat_action"] = ("rename", data.get("category_id")) if data.get("action") == "rename" else "add"
        if update.message and state == str(CAT_NAME): await finish_cat_name(update, context); return
    elif flow == "search" and state == "searching" and update.message and update.message.text:
        await receive_search(update, context); return

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it to Render Environment Variables.")
    start_health_server()
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    install_message_logging(app)
    app.add_handler(MessageHandler(filters.ALL, log_incoming), group=-2)
    app.add_handler(MessageHandler(filters.ALL, persistent_router, block=True), group=-1)
    app.job_queue.run_repeating(cleanup_job, interval=300, first=5)
    app.job_queue.run_repeating(close_expired_panels_job, interval=30, first=5)
    # Catch up immediately after a restart: all deadlines are stored as wall-clock timestamps in SQLite.

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_membership, "^check_membership$"))
    app.add_handler(CallbackQueryHandler(show_main, "^main_menu$"))
    app.add_handler(CallbackQueryHandler(close_panel, "^close_panel$"))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_book, r"^(add_book|admin_add_book)$")],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
            AUTHOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_author)],
            CATEGORY: [CallbackQueryHandler(select_category, r"^submit_category:\d+$")],
            DESCRIPTION: [CallbackQueryHandler(description_none, r"^description_none$"), CallbackQueryHandler(cancel_add_book, r"^add_cancel$"), MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
            FILE: [MessageHandler(filters.Document.ALL, get_file)],
        },
        fallbacks=[CallbackQueryHandler(cancel_add_book, "^add_cancel$")],
        allow_reentry=True,
    )
    app.add_handler(conv)

    bulk_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bulk_import_start, "^bulk_import_start$")],
        states={BULK_ZIP: [
            MessageHandler(filters.Document.ALL, bulk_receive_zip),
            CallbackQueryHandler(bulk_csv_template, "^bulk_csv_template$"),
            CallbackQueryHandler(bulk_cancel, "^bulk_cancel$"),
        ]},
        fallbacks=[CallbackQueryHandler(bulk_cancel, "^bulk_cancel$")],
        allow_reentry=True,
    )
    app.add_handler(bulk_conv)

    app.add_handler(CallbackQueryHandler(bulk_csv_template, "^bulk_csv_template$"))

    admin_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_edit_book, "^admin_edit_book$")],
        states={EDIT_ID:[MessageHandler(filters.TEXT & ~filters.COMMAND, edit_book_id)], EDIT_TITLE:[MessageHandler(filters.TEXT & ~filters.COMMAND, edit_book_title)], EDIT_AUTHOR:[MessageHandler(filters.TEXT & ~filters.COMMAND, edit_book_author)], EDIT_DESCRIPTION:[MessageHandler(filters.TEXT & ~filters.COMMAND, edit_book_finish)]},
        fallbacks=[], allow_reentry=True)
    # edit flow uses explicit continuation flags below; a single text handler completes description.
    app.add_handler(admin_edit_conv)
    cat_conv = ConversationHandler(entry_points=[CallbackQueryHandler(start_cat_add, "^admin_cat_add$"), CallbackQueryHandler(start_cat_rename, r"^admin_cat_rename:\d+$")], states={CAT_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, finish_cat_name)]}, fallbacks=[], allow_reentry=True)
    app.add_handler(cat_conv)

    app.add_handler(CallbackQueryHandler(search_start, "^search_books$"))
    app.add_handler(CallbackQueryHandler(popular, "^popular$"))
    app.add_handler(CallbackQueryHandler(my_library, "^my_library$"))
    app.add_handler(CallbackQueryHandler(my_downloads, "^my_downloads$"))
    app.add_handler(CallbackQueryHandler(my_recent, "^my_recent$"))
    app.add_handler(CallbackQueryHandler(favorite_books_view, "^favorites$"))
    app.add_handler(CallbackQueryHandler(user_books_page, r"^user_books_page:(favorites|downloads|recent):\d+$"))
    app.add_handler(CallbackQueryHandler(new_books, "^new_books$"))
    app.add_handler(CallbackQueryHandler(new_books_page, r"^new_books_page:\d+$"))
    app.add_handler(CallbackQueryHandler(popular_page, r"^popular_page:\d+$"))
    app.add_handler(CallbackQueryHandler(show_categories, "^categories$"))
    app.add_handler(CallbackQueryHandler(show_category, r"^category:\d+$"))
    app.add_handler(CallbackQueryHandler(category_page, r"^catpage:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(category_search_start, r"^category_search:\d+$"))
    app.add_handler(CallbackQueryHandler(category_search_cancel, r"^category_search_cancel:\d+$"))
    app.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.answer(), "^noop$"))
    app.add_handler(CallbackQueryHandler(search_cancel, "^search_cancel$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_search))

    app.add_handler(CallbackQueryHandler(show_book, r"^book:\d+(?::(?:popular|new|downloads|recent|favorites))?$"))
    app.add_handler(CallbackQueryHandler(favorite, r"^favorite:\d+$"))
    app.add_handler(CallbackQueryHandler(download, r"^download:\d+$"))

    app.add_handler(CallbackQueryHandler(admin_panel, "^admin_panel$"))
    app.add_handler(CallbackQueryHandler(book_management, "^book_management$"))
    app.add_handler(CallbackQueryHandler(pending_list, "^admin_pending$"))
    app.add_handler(CallbackQueryHandler(approve, r"^approve:\d+$"))
    app.add_handler(CallbackQueryHandler(reject, r"^reject:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_view, r"^admin_view:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_stats, "^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_users, "^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_user, r"^admin_user:\d+$"))
    app.add_handler(CallbackQueryHandler(user_block, r"^user_block:\d+:[01]$"))
    app.add_handler(CallbackQueryHandler(admin_categories, "^admin_categories$"))
    app.add_handler(CallbackQueryHandler(admin_cat, r"^admin_cat:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_cat_delete, r"^admin_cat_delete:\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_delete, r"^confirm_delete:\d+$"))
    app.add_handler(CallbackQueryHandler(delete, r"^delete:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_info, "^admin_broadcast_info$"))
    app.add_handler(CallbackQueryHandler(simple_admin_info, r"^admin_(published|user_books|add_book)$"))
    app.add_handler(CallbackQueryHandler(help_page, "^help$"))
    app.add_handler(CallbackQueryHandler(placeholder, "^new_books_search$"))

    logger.info("📚 Zamhrir Book Library Bot v3 is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
