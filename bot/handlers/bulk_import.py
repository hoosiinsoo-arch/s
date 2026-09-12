import asyncio
import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes, ConversationHandler

from config import OWNER_ID
from bot.database.db import add_book, publish_book, categories, get_category, book_exists

BULK_ZIP = 1


def bulk_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 دریافت نمونه CSV", callback_data="bulk_csv_template")],
        [InlineKeyboardButton("❌ لغو", callback_data="bulk_cancel")],
    ])


async def bulk_import_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != OWNER_ID:
        return ConversationHandler.END
    await q.edit_message_text(
        "<b>📦 افزودن گروهی کتاب‌ها</b>\n\n"
        "برای افزودن تعداد زیادی کتاب، یک فایل ZIP ارسال کن.\n\n"
        "<b>ساختار ZIP:</b>\n"
        "<code>books.csv</code> + فایل‌های PDF/EPUB/DOCX و...\n\n"
        "ستون‌های الزامی CSV:\n"
        "<code>filename,title,author,category</code>\n\n"
        "ستون‌های اختیاری:\n"
        "<code>description,year</code>\n\n"
        "نام فایل در ستون <code>filename</code> باید دقیقاً با فایل داخل ZIP یکی باشد.\n"
        "کتاب‌های واردشده از طرف مدیر مستقیماً منتشر می‌شوند.",
        reply_markup=bulk_keyboard(), parse_mode="HTML"
    )
    return BULK_ZIP


async def bulk_csv_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != OWNER_ID:
        return
    content = "filename,title,author,category,description,year\n001.pdf,نام کتاب,نام نویسنده,📚 ادبیات,توضیحات کتاب,1403\n002.pdf,کتاب دوم,نویسنده دوم,📖 رمان و داستان,,1402\n"
    bio = io.BytesIO(content.encode("utf-8-sig"))
    bio.name = "books.csv"
    await context.bot.send_document(
        chat_id=q.from_user.id,
        document=InputFile(bio, filename="books.csv"),
        caption="📄 نمونه فایل CSV برای ورود گروهی کتاب‌ها"
    )


async def bulk_receive_zip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID or not update.message or not update.message.document:
        return BULK_ZIP

    doc = update.message.document
    filename = doc.file_name or ""
    if not filename.lower().endswith(".zip"):
        await update.message.reply_text("❌ لطفاً فایل را با فرمت ZIP ارسال کن.", reply_markup=bulk_keyboard(), parse_mode="HTML")
        return BULK_ZIP

    status = await update.message.reply_text("⏳ فایل ZIP دریافت شد؛ در حال بررسی و آماده‌سازی کتاب‌ها...")

    with tempfile.TemporaryDirectory(prefix="zamhrir_bulk_") as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "books.zip"
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(custom_path=str(zip_path))

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                bad = zf.testzip()
                if bad:
                    raise ValueError(f"فایل ZIP خراب است: {bad}")

                members = [m for m in zf.infolist() if not m.is_dir()]
                if len(members) > 2500:
                    raise ValueError("تعداد فایل‌های ZIP بیش از حد مجاز است (حداکثر 2500 فایل).")

                csv_member = next((m for m in members if Path(m.filename).name.lower() == "books.csv"), None)
                if not csv_member:
                    raise ValueError("فایل books.csv داخل ZIP پیدا نشد.")

                csv_bytes = zf.read(csv_member)
                text = csv_bytes.decode("utf-8-sig")
                sample = text[:4096]
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(io.StringIO(text), dialect=dialect)
                if not reader.fieldnames:
                    raise ValueError("CSV فاقد عنوان ستون‌هاست.")
                reader.fieldnames = [str(x).strip().lower() if x is not None else "" for x in reader.fieldnames]
                required = {"filename", "title", "author", "category"}
                missing = required - set(reader.fieldnames)
                if missing:
                    raise ValueError("ستون‌های الزامی وجود ندارند: " + ", ".join(sorted(missing)))

                rows = list(reader)
                if not rows:
                    raise ValueError("CSV خالی است.")
                if len(rows) > 2000:
                    raise ValueError("تعداد کتاب‌ها بیش از حد مجاز است (حداکثر 2000 کتاب در هر ورود).")

                safe_members = {}
                for m in members:
                    normalized = Path(m.filename.replace("\\", "/"))
                    if normalized.is_absolute() or ".." in normalized.parts:
                        continue
                    safe_members[str(normalized)] = m
                    safe_members[normalized.name] = m

                category_map = {str(c["name"]).strip().casefold(): c["id"] for c in categories()}
                ok = duplicate = failed = 0
                errors = []
                chat_id = update.effective_chat.id

                for index, row in enumerate(rows, start=1):
                    fname = str(row.get("filename") or "").strip().replace("\\", "/")
                    title = str(row.get("title") or "").strip()
                    author = str(row.get("author") or "").strip()
                    category_name = str(row.get("category") or "").strip()
                    description = str(row.get("description") or "").strip() or None
                    year_raw = str(row.get("year") or "").strip()

                    if not fname or not title or not category_name:
                        failed += 1
                        errors.append(f"ردیف {index}: filename/title/category ناقص است")
                        continue

                    member = safe_members.get(fname) or safe_members.get(Path(fname).name)
                    if not member:
                        failed += 1
                        errors.append(f"ردیف {index}: فایل پیدا نشد → {fname}")
                        continue

                    category_id = category_map.get(category_name.casefold())
                    if not category_id:
                        failed += 1
                        errors.append(f"ردیف {index}: دسته‌بندی پیدا نشد → {category_name}")
                        continue

                    if book_exists(title, author, Path(fname).name):
                        duplicate += 1
                        continue

                    try:
                        year = int(year_raw) if year_raw else None
                    except ValueError:
                        year = None

                    # The document is sent to the admin's private chat only to obtain a
                    # Telegram file_id. The message is deleted afterwards to keep the chat clean.
                    sent = None
                    try:
                        raw = zf.read(member)
                        file_obj = io.BytesIO(raw)
                        file_obj.name = Path(fname).name
                        sent = await context.bot.send_document(
                            chat_id=chat_id,
                            document=InputFile(file_obj, filename=Path(fname).name),
                            disable_content_type_detection=False,
                        )
                        file_id = sent.document.file_id

                        book_id = add_book({
                            "title": title,
                            "author": author,
                            "category_id": category_id,
                            "language": None,
                            "description": description,
                            "year": year,
                            "format": Path(fname).suffix.lstrip(".") or None,
                            "file_id": file_id,
                            "file_name": Path(fname).name,
                            "submitted_by": OWNER_ID,
                        })
                        publish_book(book_id, OWNER_ID)
                        ok += 1
                    except Exception as exc:
                        failed += 1
                        errors.append(f"ردیف {index}: {type(exc).__name__}")
                    finally:
                        if sent:
                            try:
                                await context.bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
                            except Exception:
                                pass

                    if index % 10 == 0 or index == len(rows):
                        try:
                            await status.edit_text(
                                f"⏳ در حال ورود کتاب‌ها... <b>{index}</b> از <b>{len(rows)}</b>\n\n"
                                f"✅ موفق: {ok} | 🔁 تکراری: {duplicate} | ❌ خطادار: {failed}",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(0.1)

                report = (
                    "<b>✅ ورود گروهی تمام شد</b>\n\n"
                    "━━━━━━━━━━━━━━━━\n"
                    f"📚 کل ردیف‌ها: <b>{len(rows)}</b>\n"
                    f"✅ اضافه‌شده و منتشرشده: <b>{ok}</b>\n"
                    f"🔁 تکراری: <b>{duplicate}</b>\n"
                    f"❌ خطادار: <b>{failed}</b>"
                )
                if errors:
                    report += "\n\n<b>⚠️ چند خطای اول:</b>\n" + "\n".join(errors[:15])
                    if len(errors) > 15:
                        report += f"\n... و {len(errors)-15} خطای دیگر"

                await status.edit_text(
                    report,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📚 مدیریت کتاب‌ها", callback_data="book_management")]]),
                    parse_mode="HTML"
                )
        except zipfile.BadZipFile:
            await status.edit_text("❌ فایل ZIP معتبر نیست یا خراب شده است.")
        except Exception as exc:
            await status.edit_text(f"❌ ورود گروهی انجام نشد.\n\n<b>خطا:</b> {exc}", parse_mode="HTML")

    return ConversationHandler.END


async def bulk_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != OWNER_ID:
        return ConversationHandler.END
    await q.edit_message_text(
        "<b>📚 مدیریت کتاب‌ها</b>\n\nافزودن گروهی لغو شد.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 مدیریت کتاب‌ها", callback_data="book_management")]]),
        parse_mode="HTML"
    )
    return ConversationHandler.END
