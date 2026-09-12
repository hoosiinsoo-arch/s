from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def force_join_keyboard(channel_ok=False, group_ok=False):
    c = "🟢" if channel_ok else "🔴"
    g = "🟢" if group_ok else "🔴"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"📢 عضویت در کانال {c}", url="https://t.me/zamhrire"),
            InlineKeyboardButton(f"👥 عضویت در گروه {g}", url="https://t.me/+1Y4KqGYfHHYxNWQ0"),
        ],
        [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")]
    ])

def main_keyboard(is_owner=False):
    rows = [
        [
            InlineKeyboardButton("🔎 جستجوی کتاب", callback_data="search_books"),
            InlineKeyboardButton("🗂 دسته‌بندی کتاب‌ها", callback_data="categories"),
        ],
        [
            InlineKeyboardButton("🔥 محبوب‌ترین‌ها", callback_data="popular"),
            InlineKeyboardButton("🆕 تازه‌اضافه‌شده‌ها", callback_data="new_books"),
        ],
        [
            InlineKeyboardButton("📚 کتابخانه من", callback_data="my_library"),
            InlineKeyboardButton("⭐ علاقه‌مندی‌ها", callback_data="favorites"),
        ],
        [
            InlineKeyboardButton("➕ افزودن کتاب", callback_data="add_book"),
            InlineKeyboardButton("ℹ️ راهنما", callback_data="help"),
        ],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton("⚙️ مدیریت", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)

def add_book_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ لغو", callback_data="add_cancel")]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 مدیریت کتاب‌ها", callback_data="book_management")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ])

def book_management_keyboard(pending=0):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏳ در انتظار بررسی ({pending})", callback_data="admin_pending")],
        [InlineKeyboardButton("📚 کتاب‌های منتشرشده", callback_data="admin_published")],
        [InlineKeyboardButton("👤 کتاب‌های ارسالی کاربران", callback_data="admin_user_books")],
        [InlineKeyboardButton("➕ افزودن کتاب", callback_data="admin_add_book")],
        [InlineKeyboardButton("📦 افزودن گروهی کتاب‌ها", callback_data="bulk_import_start")],
        [InlineKeyboardButton("✏️ ویرایش کتاب", callback_data="admin_edit_book")],
        [InlineKeyboardButton("🗑 حذف کتاب", callback_data="admin_delete_book")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")],
    ])

def pending_book_keyboard(book_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأیید و انتشار", callback_data=f"approve:{book_id}"),
            InlineKeyboardButton("❌ رد کردن", callback_data=f"reject:{book_id}"),
        ],
        [InlineKeyboardButton("👁 مشاهده کتاب", callback_data=f"admin_view:{book_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_pending")],
    ])
