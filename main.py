# =========================
# IMPORTS
# =========================
import asyncio
import os
import threading
from os import environ
from datetime import datetime

from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from pyrogram.errors import FloodWait, RPCError

# ✅ SUDO DB IMPORT
from sudo import init_db, add_sudo, del_sudo, get_all_sudo, is_sudo


# =========================
# 🌐 FLASK WEB SERVER
# =========================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is alive!", 200


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )

threading.Thread(target=run_flask, daemon=True).start()


# =========================
# 🤖 BOT CONFIG
# =========================
API_ID = int(environ.get("API_ID", 31943015))
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")

OWNER_ID = int(environ.get("OWNER_ID", "8512604416"))

UNBAN_USERS = environ.get("UNBAN_USERS", "True") == "True"
BAN_CMD = ["remove_all", "removeall", "banall", "ban_all"]

app = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ✅ INIT DB
init_db()


# =========================
# 🔐 AUTH CHECK
# =========================
def is_authorized(user_id: int):
    if user_id == OWNER_ID:
        return True
    if is_sudo(user_id):
        return True
    return False


# =========================
# 📌 START
# =========================
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user = message.from_user

    await message.reply(
        "👋 Hi! I'm a Group Management Bot!\n\n"
        "🚫 Remove all members from a group\n\n"
        "Use /remove_all in group",
        quote=True
    )

    notice = f"""
🚀 <b>Bot Started</b>

👤 {user.first_name}
🆔 <code>{user.id}</code>
🕒 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}
"""
    try:
        await client.send_message(OWNER_ID, notice)
    except:
        pass


# =========================
# ➕ ADD SUDO
# =========================
@app.on_message(filters.command("addsudo") & filters.private)
async def addsudo_cmd(client, message):

    if message.from_user.id != OWNER_ID:
        return await message.reply("❌ Only Owner can add sudo users")

    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    else:
        try:
            user_id = int(message.command[1])
        except:
            return await message.reply("Usage: /addsudo user_id")

    add_sudo(user_id)

    await message.reply(f"✅ Added {user_id} as Sudo User")


# =========================
# ➖ DEL SUDO
# =========================
@app.on_message(filters.command("delsudo") & filters.private)
async def delsudo_cmd(client, message):

    if message.from_user.id != OWNER_ID:
        return await message.reply("❌ Only Owner can remove sudo users")

    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    else:
        try:
            user_id = int(message.command[1])
        except:
            return await message.reply("Usage: /delsudo user_id")

    del_sudo(user_id)

    await message.reply(f"🗑 Removed {user_id} from Sudo Users")


# =========================
# 📜 SUDO LIST
# =========================
@app.on_message(filters.command("sudolist") & filters.private)
async def sudolist_cmd(client, message):

    sudo_users = get_all_sudo()

    text = f"👑 Owner:\n<code>{OWNER_ID}</code>\n\n⚡ Sudo Users:\n"

    if not sudo_users:
        text += "No sudo users added"
    else:
        for user in sudo_users:
            text += f"• <code>{user}</code>\n"

    await message.reply(text)


# =========================
# 🚫 REMOVE ALL
# =========================
@app.on_message(filters.command(BAN_CMD) & (filters.group | filters.channel))
async def remove_all_users(client, message):

    user_id = message.from_user.id

    # ✅ AUTH CHECK
    if not is_authorized(user_id):
        return await message.reply("❌ You are not authorized to use this command")

    chat_id = message.chat.id

    bot_admin = await client.get_chat_member(chat_id, "me")
    if not bot_admin.privileges or not bot_admin.privileges.can_restrict_members:
        await message.reply("🚨 I need 'Ban Users' permission!")
        return

    count = 0
    update_message = await message.reply(
        "🔄 Removing members...\nProgress: 0"
    )

    async for member in client.get_chat_members(chat_id):

        if member.status in (
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER
        ):
            continue

        try:
            await client.ban_chat_member(chat_id, member.user.id)
            count += 1

            if count % 10 == 0:
                await update_message.edit(f"Removed: {count}")

        except FloodWait as e:
            await asyncio.sleep(e.value)
        except RPCError:
            pass

    await update_message.edit(f"✅ Completed\nRemoved: {count}")


# =========================
# 🚀 RUN
# =========================
if __name__ == "__main__":
    print("Bot running...")
    app.run()
