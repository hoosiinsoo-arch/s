from bot.database.db import get_session, set_session, clear_session

async def resume_session(update, context):
    user = update.effective_user
    if not user:
        return False
    s = get_session(user.id)
    if not s:
        return False
    context.user_data["_persistent_session"] = s
    return s
