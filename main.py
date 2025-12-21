# Description: A simple Telegram Bot to remove all members from a group.
# By: MrTamilKiD
# Updates: "For more updates join @KR_BotX"
# Created on: 2025-03-07
# Last Updated: 2025-03-07

import asyncio
import os
import threading
from os import environ

from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from pyrogram.errors import FloodWait, RPCError


# =========================
# 🌐 FLASK WEB SERVER (FOR KOYEB)
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

# daemon=True => bot band ho to flask bhi clean exit kare
threading.Thread(target=run_flask, daemon=True).start()


# =========================
# 🤖 TELEGRAM BOT CONFIG
# =========================
API_ID = int(environ.get("API_ID", 23631217))
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")

UNBAN_USERS = environ.get("UNBAN_USERS", "True") == "True"
BAN_CMD = ["remove_all", "removeall", "banall", "ban_all"]

app = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# =========================
# 📌 START COMMAND
# =========================
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply(
        "👋 Hi! I'm a Group Management Bot!\n\n"
        "✨ What I can do:\n"
        "🚫 Remove all members from a group\n\n"
        "📝 How to use me:\n"
        "1️⃣ Add me as admin in your group\n"
        "2️⃣ Give me 'Ban Users' permission\n"
        "3️⃣ Use /remove_all command\n\n"
        "⚠️ Important: I need 'Ban Users' permission to work!",
        reply_markup=Markup(
            [
                [
                    Button("👨‍💻 Developer", url="https://t.me/mimam_officialx"),
                    Button("💬 Support", url="https://t.me/MRN_Chat_Group"),
                ],
                [Button("⭐ Source Code", url="https://t.me/mimam_officialx")],
            ]
        ),
        quote=True,
        disable_web_page_preview=True,
    )


# =========================
# 📌 HELP COMMAND
# =========================
@app.on_message(filters.command("help") & filters.private)
async def help(client, message):
    await message.reply(
        "🤖 Simple Bot Guide:\n\n"
        "📍 Commands:\n"
        "/remove_all - Remove everyone from group\n\n"
        "📌 Quick Setup:\n"
        "1️⃣ Make me admin\n"
        "2️⃣ Give 'Ban Users' permission\n"
        "3️⃣ That's it!",
        disable_web_page_preview=True,
        quote=True,
    )


# =========================
# 🚫 REMOVE ALL USERS
# =========================
@app.on_message(filters.command(BAN_CMD) & (filters.group | filters.channel))
async def remove_all_users(client, message):
    chat_id = message.chat.id

    bot_admin = await client.get_chat_member(chat_id, "me")
    if not bot_admin.privileges or not bot_admin.privileges.can_restrict_members:
        await message.reply("🚨 I need 'Ban Users' permission to remove members!")
        return

    count = 0
    update_message = await message.reply(
        "🔄 Starting to remove members...\n\n⌛ Please wait...\n\n🔹 Progress: 0",
        quote=True
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
                await update_message.edit(
                    f"🔄 Progress Update:\n\n✅ Members removed: {count}"
                )

        except FloodWait as e:
            await asyncio.sleep(e.value)
        except RPCError:
            pass

    if UNBAN_USERS:
        async for member in client.get_chat_members(
            chat_id, filter=enums.ChatMembersFilter.BANNED
        ):
            try:
                await client.unban_chat_member(chat_id, member.user.id)
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except RPCError:
                pass

    await update_message.edit(
        f"🎉 Operation Complete!\n\n"
        f"👥 Total Members Removed: {count}"
    )


# =========================
# 🚀 RUN BOT
# =========================
if __name__ == "__main__":
    print("Bot + Web Server running...")
    app.run()

