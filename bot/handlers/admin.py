from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime, timedelta
from config import OWNER_ID
from bot.database.db import *
from bot.database.db import admin_stats as get_admin_stats, set_session, clear_session

def owner_only(uid): return uid == OWNER_ID

def admin_root_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 مدیریت کتاب‌ها", callback_data="book_management"), InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("🗂 مدیریت دسته‌بندی‌ها", callback_data="admin_categories"), InlineKeyboardButton("📊 آمار کامل", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 اطلاع‌رسانی", callback_data="admin_broadcast_info")],
        [InlineKeyboardButton("🔒 بستن پنل", callback_data="close_panel")],
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
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید و انتشار",callback_data=f"approve:{book_id}"),InlineKeyboardButton("❌ رد کردن",callback_data=f"reject:{book_id}")],[InlineKeyboardButton("👁 مشاهده کتاب",callback_data=f"admin_view:{book_id}")],[InlineKeyboardButton("🔙 بازگشت",callback_data="admin_pending")]])

async def admin_panel(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    s=get_admin_stats()
    await q.edit_message_text(f"<b>⚙️ پنل مدیریت</b>\n\n━━━━━━━━━━━━━━━━\n👥 کاربران: <b>{s['users']}</b>\n📚 کتاب‌ها: <b>{s['books']}</b>\n⏳ در انتظار: <b>{s['pending']}</b>\n\n<b>بخش مدیریتی را انتخاب کنید:</b>",reply_markup=admin_root_kb(),parse_mode="HTML")
    stamp=datetime.now()
    set_panel(q.message.chat_id,q.message.message_id,stamp.isoformat(timespec="seconds"),(stamp+timedelta(minutes=10)).isoformat(timespec="seconds"))

async def book_management(update,context):
    q=update.callback_query; await q.answer()
    if owner_only(q.from_user.id): await q.edit_message_text("<b>📚 مدیریت کتاب‌ها</b>\n\n━━━━━━━━━━━━━━━━\nاز گزینه‌های زیر انتخاب کنید:",reply_markup=book_management_keyboard(pending_count()),parse_mode="HTML")

async def pending_list(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    books=pending_books()
    if not books:
        await q.edit_message_text("<b>⏳ در انتظار بررسی</b>\n\n━━━━━━━━━━━━━━━━\nموردی وجود ندارد.",reply_markup=book_management_keyboard(0),parse_mode="HTML"); return
    b=books[0]; who=b['first_name'] or b['username'] or str(b['submitted_by'])
    text=f"<b>⏳ درخواست بعدی</b>\n\n📖 <b>{b['title']}</b>\n✍️ {b['author'] or 'نامشخص'}\n👤 ارسال‌کننده: <code>{who}</code>\n🆔 <code>{b['submitted_by']}</code>\n📌 درخواست: <code>{b['id']}</code>\n\nتعداد در صف: <b>{len(books)}</b>"
    await q.edit_message_text(text,reply_markup=pending_book_keyboard(b['id']),parse_mode="HTML")

async def approve(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    publish_book(int(q.data.split(':')[1]),OWNER_ID); await pending_list(update,context)
async def reject(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    reject_book(int(q.data.split(':')[1]),"رد شده توسط مدیر"); await pending_list(update,context)

async def admin_view(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    b=get_book(int(q.data.split(':')[1]))
    if not b: await q.answer("کتاب پیدا نشد.",show_alert=True); return
    text=f"<b>👁 مشاهده کتاب</b>\n\n📖 <b>{b['title']}</b>\n✍️ {b['author'] or 'نامشخص'}\n🗂 {b['category_name'] or 'نامشخص'}\n📝 {b['description'] or 'ندارد'}\n📌 وضعیت: <b>{b['status']}</b>\n👤 ارسال‌کننده: <code>{b['submitted_by']}</code>\n👁 {b['views']} | ⬇️ {b['downloads']}"
    await q.edit_message_text(text,reply_markup=pending_book_keyboard(b['id']) if b['status']=='pending' else InlineKeyboardMarkup([[InlineKeyboardButton("🗑 حذف کتاب",callback_data=f"confirm_delete:{b['id']}")],[InlineKeyboardButton("🔙 مدیریت کتاب‌ها",callback_data="book_management")]]),parse_mode="HTML")

async def admin_stats(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    s=admin_stats_data()
    text=(f"<b>📊 آمار کامل کتابخانه</b>\n\n━━━━━━━━━━━━━━━━\n"
          f"👥 کل کاربران: <b>{s['users']}</b>\n🟢 فعال در ۳۰ روز اخیر: <b>{s['active_30']}</b>\n"
          f"🆕 امروز: <b>{s['new_today']}</b>\n📅 این هفته: <b>{s['new_week']}</b>\n📆 این ماه: <b>{s['new_month']}</b>\n🚫 مسدود: <b>{s['blocked']}</b>\n\n"
          f"📚 کل کتاب‌ها: <b>{s['books']}</b>\n✅ منتشرشده: <b>{s['published']}</b>\n⏳ در انتظار: <b>{s['pending']}</b>\n❌ ردشده: <b>{s['rejected']}</b>\n\n"
          f"👁 بازدید یکتا: <b>{s['views']}</b>\n📥 دانلود یکتا: <b>{s['downloads']}</b>\n⭐ علاقه‌مندی‌ها: <b>{s['favorites']}</b>\n🔎 جستجوها: <b>{s['searches']}</b>\n📈 کل فعالیت ثبت‌شده: <b>{s['activity']}</b>")
    await q.edit_message_text(text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 بروزرسانی",callback_data="admin_stats")],[InlineKeyboardButton("🔙 مدیریت",callback_data="admin_panel")]]),parse_mode="HTML")

def admin_stats_data(): return get_admin_stats()

async def admin_users(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    users=find_users("",20)
    buttons=[[InlineKeyboardButton(f"👤 {u['first_name'] or u['username'] or u['telegram_id']} — {u['telegram_id']}",callback_data=f"admin_user:{u['telegram_id']}")] for u in users]
    buttons.append([InlineKeyboardButton("🔙 مدیریت",callback_data="admin_panel")])
    await q.edit_message_text(f"<b>👥 مدیریت کاربران</b>\n\n━━━━━━━━━━━━━━━━\nکل کاربران: <b>{total_users()}</b>\nبرای مشاهده جزئیات یک کاربر انتخاب کنید:",reply_markup=InlineKeyboardMarkup(buttons),parse_mode="HTML")

async def admin_user(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    uid=int(q.data.split(':')[1]); u=get_user(uid)
    if not u: await q.answer("کاربر پیدا نشد.",show_alert=True); return
    blocked=bool(u['is_blocked']); text=(f"<b>👤 پروفایل کاربر</b>\n\n🆔 <code>{uid}</code>\n👤 {u['first_name'] or 'بدون نام'}\n🔗 @{u['username'] or 'ندارد'}\n📅 عضویت: {u['created_at']}\n🕐 آخرین فعالیت: {u['last_seen_at'] or 'ندارد'}\n📈 کل فعالیت: <b>{user_activity_count(uid)}</b>\n📖 بازدید کتاب: <b>{user_activity_count(uid,'view_book')}</b>\n📥 دانلود: <b>{user_activity_count(uid,'download_book')}</b>\n🚦 وضعیت: <b>{'مسدود' if blocked else 'فعال'}</b>")
    buttons=[[InlineKeyboardButton("✅ رفع مسدودی" if blocked else "🚫 مسدود کردن",callback_data=f"user_block:{uid}:{0 if blocked else 1}")],[InlineKeyboardButton("🔙 کاربران",callback_data="admin_users")]]
    await q.edit_message_text(text,reply_markup=InlineKeyboardMarkup(buttons),parse_mode="HTML")

async def user_block(update,context):
    q=update.callback_query; await q.answer()
    if owner_only(q.from_user.id): set_user_blocked(int(q.data.split(':')[1]),int(q.data.split(':')[2])); await admin_user(update,context)

async def admin_categories(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    cats=categories(); buttons=[[InlineKeyboardButton(c['name'],callback_data=f"admin_cat:{c['id']}")] for c in cats]
    buttons += [[InlineKeyboardButton("➕ افزودن دسته‌بندی",callback_data="admin_cat_add")],[InlineKeyboardButton("🔙 مدیریت",callback_data="admin_panel")]]
    await q.edit_message_text("<b>🗂 مدیریت دسته‌بندی‌ها</b>\n\n━━━━━━━━━━━━━━━━\nدسته‌بندی موردنظر را انتخاب کنید:",reply_markup=InlineKeyboardMarkup(buttons),parse_mode="HTML")

async def admin_cat(update,context):
    q=update.callback_query; await q.answer();
    if owner_only(q.from_user.id):
        cid=int(q.data.split(':')[1]); c=get_category(cid)
        await q.edit_message_text(f"<b>🗂 {c['name'] if c else 'دسته‌بندی'}</b>\n\n━━━━━━━━━━━━━━━━\nکتاب‌های این دسته: <b>{category_count(cid)}</b>",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✏️ تغییر نام",callback_data=f"admin_cat_rename:{cid}")],[InlineKeyboardButton("🗑 حذف",callback_data=f"admin_cat_delete:{cid}")],[InlineKeyboardButton("🔙 دسته‌بندی‌ها",callback_data="admin_categories")]]),parse_mode="HTML")

async def admin_cat_delete(update,context):
    q=update.callback_query; await q.answer()
    if owner_only(q.from_user.id):
        ok=delete_category(int(q.data.split(':')[1])); await q.answer("حذف شد." if ok else "این دسته کتاب دارد و حذف نمی‌شود.",show_alert=True); await admin_categories(update,context)

async def simple_admin_info(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    data=q.data
    if data=="admin_published":
        rows=all_published_books(30); text=f"<b>📚 منتشرشده‌ها</b>\n\n━━━━━━━━━━━━━━━━\nتعداد: <b>{published_count()}</b>"
        kb=[[InlineKeyboardButton(f"📖 {b['title']}",callback_data=f"admin_view:{b['id']}")] for b in rows]
        kb.append([InlineKeyboardButton("🔙 مدیریت کتاب‌ها",callback_data="book_management")]); await q.edit_message_text(text,reply_markup=InlineKeyboardMarkup(kb),parse_mode="HTML")
    elif data=="admin_user_books":
        rows=all_user_books(30); kb=[[InlineKeyboardButton(f"📖 {b['title']} — {b['submitted_by']}",callback_data=f"admin_view:{b['id']}")] for b in rows]; kb.append([InlineKeyboardButton("🔙 مدیریت",callback_data="book_management")]); await q.edit_message_text(f"<b>👤 کتاب‌های ارسالی کاربران</b>\n\n━━━━━━━━━━━━━━━━\nتعداد نمایش: <b>{len(rows)}</b>",reply_markup=InlineKeyboardMarkup(kb),parse_mode="HTML")
    elif data=="admin_edit_book": await q.edit_message_text("<b>✏️ ویرایش کتاب</b>\n\nبرای ویرایش دقیق، شناسه کتاب را از فهرست منتشرشده انتخاب کنید.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📚 انتخاب کتاب",callback_data="admin_published")],[InlineKeyboardButton("🔙 مدیریت",callback_data="book_management")]]),parse_mode="HTML")
    elif data=="admin_delete_book": await q.edit_message_text("<b>🗑 حذف کتاب</b>\n\nکتاب را از فهرست منتشرشده انتخاب کنید تا امکان حذف آن نمایش داده شود.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📚 انتخاب کتاب",callback_data="admin_published")],[InlineKeyboardButton("🔙 مدیریت",callback_data="book_management")]]),parse_mode="HTML")
    else: await q.edit_message_text("<b>➕ افزودن کتاب</b>\n\nفرم افزودن کتاب مدیر از همین بخش قابل استفاده است.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ شروع افزودن",callback_data="admin_add_book")],[InlineKeyboardButton("🔙 مدیریت",callback_data="book_management")]]),parse_mode="HTML")

async def confirm_delete(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    bid=int(q.data.split(':')[1]); b=get_book(bid)
    await q.edit_message_text(f"<b>⚠️ حذف کتاب</b>\n\n📖 {b['title'] if b else 'نامشخص'}\n\nاین عملیات اطلاعات کتاب، علاقه‌مندی‌ها و آمار مرتبط را حذف می‌کند.\nآیا مطمئن هستید؟",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑 بله، حذف شود",callback_data=f"delete:{bid}")],[InlineKeyboardButton("❌ انصراف",callback_data="admin_published")]]),parse_mode="HTML")
async def delete(update,context):
    q=update.callback_query; await q.answer()
    if owner_only(q.from_user.id): delete_book(int(q.data.split(':')[1])); await q.answer("کتاب حذف شد.",show_alert=True); await simple_admin_info(type('X',(),{'callback_query':q})(),context)

async def admin_broadcast_info(update,context):
    q=update.callback_query; await q.answer();
    if owner_only(q.from_user.id): await q.edit_message_text("<b>📢 اطلاع‌رسانی</b>\n\nقابلیت ارسال اعلان عمومی در این نسخه به‌صورت ایمن آماده‌سازی شده است. برای جلوگیری از ارسال ناخواسته، قبل از افزودن ارسال انبوه آن را با تأیید دومرحله‌ای فعال می‌کنیم.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 مدیریت",callback_data="admin_panel")]]),parse_mode="HTML")


EDIT_ID, EDIT_TITLE, EDIT_AUTHOR, EDIT_DESCRIPTION = range(100, 104)
CAT_NAME = 110

async def start_edit_book(update, context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    context.user_data['admin_edit']={}
    set_session(q.from_user.id, 'admin_edit', EDIT_ID, {})
    await q.edit_message_text("<b>✏️ ویرایش کتاب</b>\n\nشناسه عددی کتاب را ارسال کنید.",parse_mode="HTML")
    return EDIT_ID

async def edit_book_id(update,context):
    try: bid=int(update.message.text.strip()); b=get_book(bid)
    except Exception: b=None
    if not b:
        await update.message.reply_text("❌ شناسه کتاب معتبر نیست. دوباره ارسال کنید."); return EDIT_TITLE
    context.user_data['admin_edit']={'book_id':bid}
    set_session(update.effective_user.id, 'admin_edit', EDIT_TITLE, context.user_data['admin_edit'])
    await update.message.reply_text(f"<b>عنوان فعلی:</b> {b['title']}\n\nعنوان جدید را ارسال کنید.",parse_mode="HTML"); return EDIT_TITLE

async def edit_book_title(update,context):
    context.user_data['admin_edit']['title']=update.message.text.strip()
    set_session(update.effective_user.id, 'admin_edit', EDIT_AUTHOR, context.user_data['admin_edit'])
    b=get_book(context.user_data['admin_edit']['book_id'])
    await update.message.reply_text(f"<b>نویسنده فعلی:</b> {b['author'] or 'ندارد'}\n\nنویسنده جدید را ارسال کنید.\nبرای حفظ قبلی: <code>-</code>",parse_mode="HTML"); return EDIT_AUTHOR

async def edit_book_author(update,context):
    e=context.user_data['admin_edit']; e['author']=None if update.message.text.strip()=="-" else update.message.text.strip()
    set_session(update.effective_user.id, 'admin_edit', EDIT_DESCRIPTION, e)
    await update.message.reply_text("<b>📝 توضیحات جدید</b>\nبرای حذف توضیحات <code>-</code> ارسال کنید.",parse_mode="HTML"); return EDIT_DESCRIPTION

async def edit_book_finish(update,context):
    e=context.user_data['admin_edit']; desc=None if update.message.text.strip()=="-" else update.message.text.strip()
    update_book(e['book_id'],title=e.get('title'),author=e.get('author'),description=desc)
    context.user_data.pop('admin_edit',None)
    clear_session(update.effective_user.id)
    await update.message.reply_text("<b>✅ کتاب با موفقیت ویرایش شد.</b>",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📚 مدیریت کتاب‌ها",callback_data="book_management")]]),parse_mode="HTML")
    return -1

async def start_cat_add(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    context.user_data['admin_cat_action']='add'
    set_session(q.from_user.id, 'admin_cat', CAT_NAME, {'action':'add'})
    await q.edit_message_text("<b>➕ افزودن دسته‌بندی</b>\n\nنام دسته‌بندی را ارسال کنید.",parse_mode="HTML"); return CAT_NAME

async def start_cat_rename(update,context):
    q=update.callback_query; await q.answer()
    if not owner_only(q.from_user.id): return
    cid=int(q.data.split(':')[1]); context.user_data['admin_cat_action']=('rename',cid)
    set_session(q.from_user.id, 'admin_cat', CAT_NAME, {'action':'rename','category_id':cid})
    await q.edit_message_text("<b>✏️ تغییر نام دسته‌بندی</b>\n\nنام جدید را ارسال کنید.",parse_mode="HTML"); return CAT_NAME

async def finish_cat_name(update,context):
    name=update.message.text.strip()
    if len(name)<2: await update.message.reply_text("❌ نام خیلی کوتاه است."); return CAT_NAME
    action=context.user_data.pop('admin_cat_action',None)
    clear_session(update.effective_user.id)
    try:
        if action=='add': add_category(name); msg="✅ دسته‌بندی اضافه شد."
        else: rename_category(action[1],name); msg="✅ نام دسته‌بندی تغییر کرد."
    except Exception: msg="❌ این نام قبلاً وجود دارد."
    await update.message.reply_text(msg,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂 دسته‌بندی‌ها",callback_data="admin_categories")]]),parse_mode="HTML")
    return -1
