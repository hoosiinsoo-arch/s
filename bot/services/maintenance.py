from datetime import datetime, timedelta
from bot.database.db import get_expired_messages, remove_logged_message, remove_logged_messages_before, get_expired_panels, clear_panel

CLEANUP_SECONDS = 2 * 60 * 60
PANEL_SECONDS = 10 * 60

async def cleanup_job(context):
    cutoff = (datetime.now() - timedelta(seconds=CLEANUP_SECONDS)).isoformat(timespec="seconds")
    for row in get_expired_messages(cutoff):
        try:
            await context.bot.delete_message(chat_id=row["chat_id"], message_id=row["message_id"])
        except Exception:
            pass
        remove_logged_message(row["id"])
    # Also remove stale DB records even when Telegram already removed a message.
    remove_logged_messages_before(cutoff)

async def close_expired_panels_job(context):
    now = datetime.now().isoformat(timespec="seconds")
    for row in get_expired_panels(now):
        try:
            await context.bot.delete_message(chat_id=row["chat_id"], message_id=row["message_id"])
        except Exception:
            pass
        clear_panel(row["chat_id"], row["message_id"])
