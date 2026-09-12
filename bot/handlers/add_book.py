from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.database.db import add_book, upsert_user, categories, get_category, set_session, clear_session
from bot.keyboards.main import add_book_keyboard, main_keyboard
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

TITLE, AUTHOR, CATEGORY, DESCRIPTION, FILE = range(5)


async def start_add_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["book_submission"] = {"admin_add": query.data == "admin_add_book"}
    set_session(query.from_user.id, "add_book", TITLE, context.user_data["book_submission"])
    await query.edit_message_text(
        "<b>➕ افزودن کتاب</b>\n\n"
        "<b>نام کتاب را ارسال کنید.</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "<blockquote><b>توجه:</b>\n"
        "کتاب پس از بررسی و تأیید در کتابخانه عمومی منتشر می‌شود.</blockquote>",
        reply_markup=add_book_keyboard(),
        parse_mode="HTML",
    )
    return TITLE


async def get_title(update, context):
    context.user_data["book_submission"]["title"] = update.message.text.strip()
    set_session(update.effective_user.id, "add_book", AUTHOR, context.user_data["book_submission"])
    await update.message.reply_text(
        "<b>✍️ نام نویسنده را ارسال کنید.</b>",
        reply_markup=add_book_keyboard(), parse_mode="HTML"
    )
    return AUTHOR


async def get_author(update, context):
    context.user_data["book_submission"]["author"] = update.message.text.strip()
    set_session(update.effective_user.id, "add_book", CATEGORY, context.user_data["book_submission"])
    cats = categories()
    rows = []
    for i in range(0, len(cats), 2):
        pair = cats[i:i + 2]
        row = [InlineKeyboardButton(pair[0]["name"], callback_data=f"submit_category:{pair[0]['id']}")]
        if len(pair) > 1:
            row.append(InlineKeyboardButton(pair[1]["name"], callback_data=f"submit_category:{pair[1]['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ لغو", callback_data="add_cancel")])
    await update.message.reply_text(
        "<b>🗂 دسته‌بندی کتاب را انتخاب کنید.</b>",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML"
    )
    return CATEGORY


async def select_category(update, context):
    q = update.callback_query
    await q.answer()
    category_id = int(q.data.split(":")[1])
    cat = get_category(category_id)
    context.user_data["book_submission"]["category_id"] = category_id
    context.user_data["book_submission"]["category"] = cat["name"] if cat else "نامشخص"
    set_session(q.from_user.id, "add_book", DESCRIPTION, context.user_data["book_submission"])

    await q.edit_message_text(
        "<b>📝 توضیحات کتاب را وارد کنید.</b>\n\n"
        "<i>اگر توضیحی ندارد، دکمه «ندارد» را بزنید.</i>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ندارد", callback_data="description_none")],
            [InlineKeyboardButton("🔙 لغو", callback_data="add_cancel")],
        ]),
        parse_mode="HTML"
    )
    return DESCRIPTION


async def get_description(update, context):
    context.user_data["book_submission"]["description"] = update.message.text.strip()
    set_session(update.effective_user.id, "add_book", FILE, context.user_data["book_submission"])
    await ask_for_file(update.message, context)
    return FILE


async def description_none(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["book_submission"]["description"] = None
    set_session(q.from_user.id, "add_book", FILE, context.user_data["book_submission"])
    await q.edit_message_text(
        "<b>📎 حالا فایل کتاب را به‌صورت Document ارسال کنید.</b>\n\n"
        "فقط فایل‌هایی را ارسال کنید که حق انتشار آن‌ها را دارید.",
        reply_markup=add_book_keyboard(), parse_mode="HTML"
    )
    return FILE


async def ask_for_file(message, context):
    await message.reply_text(
        "<b>📎 حالا فایل کتاب را به‌صورت Document ارسال کنید.</b>\n\n"
        "فقط فایل‌هایی را ارسال کنید که حق انتشار آن‌ها را دارید.",
        reply_markup=add_book_keyboard(), parse_mode="HTML"
    )


async def get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text(
            "<b>⚠️ لطفاً خود فایل کتاب را به‌صورت Document ارسال کنید.</b>",
            reply_markup=add_book_keyboard(), parse_mode="HTML"
        )
        return FILE

    user = update.effective_user
    upsert_user(user)
    s = context.user_data["book_submission"]
    file = update.message.document

    book_id = add_book({
        "title": s["title"],
        "author": s["author"],
        "category_id": s.get("category_id"),
        "language": None,
        "description": s.get("description"),
        "year": None,
        "format": file.file_name.rsplit(".", 1)[-1] if "." in file.file_name else None,
        "file_id": file.file_id,
        "file_name": file.file_name,
        "submitted_by": user.id,
    })

    if s.get("admin_add"):
        from config import OWNER_ID
        from bot.database.db import publish_book
        publish_book(book_id, OWNER_ID)

    context.user_data.pop("book_submission", None)
    clear_session(user.id)

    await update.message.reply_text(
        f"<b>✅ کتاب شما ثبت شد.</b>\n\n"
        f"<b>📚 عنوان:</b> {s['title']}\n"
        f"<b>🗂 دسته‌بندی:</b> {s.get('category', 'نامشخص')}\n"
        f"<b>🆔 شناسه درخواست:</b> {book_id}\n\n"
        "<blockquote>" + ("کتاب مدیر مستقیماً در کتابخانه منتشر شد." if s.get("admin_add") else "پس از بررسی مدیر، در صورت تأیید در کتابخانه عمومی منتشر می‌شود.") + "</blockquote>",
        reply_markup=main_keyboard(user.id == 7629008069),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cancel_add_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("book_submission", None)
    clear_session(query.from_user.id)
    await query.edit_message_text(
        "<b>📚 به کتابخانه زمهریر خوش آمدید</b>\n\n"
        "<b>افزودن کتاب لغو شد.</b>",
        reply_markup=main_keyboard(query.from_user.id == 7629008069),
        parse_mode="HTML",
    )
    return ConversationHandler.END
