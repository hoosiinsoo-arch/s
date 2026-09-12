from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def categories_keyboard(categories):
    rows = []
    for i in range(0, len(categories), 2):
        pair = categories[i:i + 2]
        row = [InlineKeyboardButton(pair[0]["name"], callback_data=f"category:{pair[0]['id']}")]
        if len(pair) > 1:
            row.append(InlineKeyboardButton(pair[1]["name"], callback_data=f"category:{pair[1]['id']}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("🔎 جستجوی کتاب", callback_data="category_search:0"),
        InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(rows)


def category_books_keyboard(category_id, page, total_pages, books=None):
    books = books or []
    rows = []

    # هر کتاب یک دکمه قابل انتخاب دارد.
    for b in books:
        title = b["title"] or "بدون عنوان"
        rows.append([
            InlineKeyboardButton(f"📖 {title}", callback_data=f"book:{b['id']}")
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"catpage:{category_id}:{page - 1}"))
    nav.append(InlineKeyboardButton(f"صفحه {page + 1} از {total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("➡️ صفحه بعد", callback_data=f"catpage:{category_id}:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("🔎 جستجوی کتاب", callback_data=f"category_search:{category_id}"),
        InlineKeyboardButton("🔙 دسته‌بندی‌ها", callback_data="categories"),
    ])
    rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def category_search_keyboard(category_id):
    if category_id == 0:
        back = "categories"
    else:
        back = f"category:{category_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ لغو جستجو", callback_data=f"category_search_cancel:{category_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=back)],
    ])
