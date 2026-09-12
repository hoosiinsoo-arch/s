import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.database.db import categories, get_category, category_books, published_books
from bot.keyboards.categories import categories_keyboard, category_books_keyboard, category_search_keyboard

PAGE_SIZE = 10


async def show_categories(update, context):
    q = update.callback_query
    await q.answer()
    cats = categories()
    await q.edit_message_text(
        "<b>🗂 دسته‌بندی کتاب‌ها</b>\n\n━━━━━━━━━━━━━━━━\n"
        "<b>دسته‌بندی موردنظر را انتخاب کنید:</b>",
        reply_markup=categories_keyboard(cats), parse_mode="HTML"
    )


async def show_category(update, context):
    q = update.callback_query
    await q.answer()
    category_id = int(q.data.split(":")[1])
    await render_category(q, category_id, 0)


def _text(cat, books, page, total_pages):
    lines = [f"<b>{cat['name']}</b>", "", "━━━━━━━━━━━━━━━━"]
    if not books:
        lines.append("<b>❌ هنوز کتابی در این دسته منتشر نشده است.</b>")
    else:
        lines.append(f"<b>📚 {len(books)} کتاب در این صفحه</b>")
        lines.append("")
        lines.append("<i>برای مشاهده مشخصات کتاب، روی دکمه آن بزنید.</i>")
    lines.extend(["", "━━━━━━━━━━━━━━━━", f"<b>📄 صفحه {page + 1} از {total_pages}</b>"])
    return "\n".join(lines)


async def render_category(q, category_id, page):
    cat = get_category(category_id)
    if not cat:
        await q.answer("دسته‌بندی پیدا نشد.", show_alert=True)
        return
    all_books = category_books(category_id)
    total_pages = max(1, math.ceil(len(all_books) / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    books = all_books[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    await q.edit_message_text(
        _text(cat, books, page, total_pages),
        reply_markup=category_books_keyboard(category_id, page, total_pages, books),
        parse_mode="HTML"
    )


async def category_page(update, context):
    q = update.callback_query
    await q.answer()
    _, category_id, page = q.data.split(":")
    await render_category(q, int(category_id), int(page))


async def category_search_start(update, context):
    q = update.callback_query
    await q.answer()
    category_id = int(q.data.split(":")[1])
    if category_id == 0:
        await q.edit_message_text(
            "<b>🔎 جستجوی کتاب</b>\n\n<b>یک عبارت جستجو ارسال کنید.</b>\n\n"
            "━━━━━━━━━━━━━━━━\n<i>این جستجو در همه کتاب‌های منتشرشده انجام می‌شود.</i>",
            reply_markup=category_search_keyboard(0), parse_mode="HTML"
        )
        context.user_data["category_searching"] = 0
    else:
        cat = get_category(category_id)
        context.user_data["category_searching"] = category_id
        await q.edit_message_text(
            f"<b>🔎 جستجو در {cat['name']}</b>\n\n"
            "<b>نام کتاب، نویسنده یا بخشی از عنوان را ارسال کنید.</b>\n\n"
            "━━━━━━━━━━━━━━━━\n"
            f"<i>فقط کتاب‌های دسته «{cat['name']}» جستجو می‌شوند.</i>",
            reply_markup=category_search_keyboard(category_id), parse_mode="HTML"
        )


async def category_search_cancel(update, context):
    q = update.callback_query
    await q.answer()
    category_id = int(q.data.split(":")[1])
    context.user_data.pop("category_searching", None)
    if category_id == 0:
        cats = categories()
        await q.edit_message_text(
            "<b>🗂 دسته‌بندی کتاب‌ها</b>\n\n━━━━━━━━━━━━━━━━\n"
            "<b>دسته‌بندی موردنظر را انتخاب کنید:</b>",
            reply_markup=categories_keyboard(cats), parse_mode="HTML"
        )
    else:
        await render_category(q, category_id, 0)


async def receive_category_search(update, context):
    if "category_searching" not in context.user_data:
        return False
    category_id = int(context.user_data.pop("category_searching"))
    query = update.message.text.strip()
    rows = category_books(category_id, query) if category_id else published_books(query)
    buttons = []
    for b in rows[:30]:
        buttons.append([InlineKeyboardButton(
            f"📖 {b['title']} — {b['author'] or 'نامشخص'}",
            callback_data=f"book:{b['id']}"
        )])
    if category_id:
        back = f"category:{category_id}"
        label = "🔙 بازگشت به دسته"
    else:
        back = "categories"
        label = "🔙 دسته‌بندی‌ها"
    buttons.append([
        InlineKeyboardButton(label, callback_data=back),
        InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")
    ])
    title = get_category(category_id)['name'] if category_id else "همه کتاب‌ها"
    result_text = (
        f"<b>🔎 نتایج جستجو در {title}</b>\n\n━━━━━━━━━━━━━━━━\n"
        f"<b>{len(rows)}</b> نتیجه پیدا شد.\n\n<i>برای مشاهده مشخصات کتاب، روی آن بزنید.</i>"
        if rows else
        f"<b>🔎 نتایج جستجو در {title}</b>\n\n━━━━━━━━━━━━━━━━\n❌ کتابی پیدا نشد."
    )
    await update.message.reply_text(
        result_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML"
    )
    return True
