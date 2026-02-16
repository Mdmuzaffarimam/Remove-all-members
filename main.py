import asyncio
import os
import threading
import aiosqlite
from os import environ
from datetime import datetime

from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup, CallbackQuery
from pyrogram.errors import FloodWait, RPCError

# =========================
# 🌐 FLASK WEB SERVER
# =========================
flask_app = Flask(__name__)
@flask_app.route("/")
def home(): return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_flask, daemon=True).start()

# =========================
# 🤖 CONFIG & DATABASE
# =========================
API_ID = int(environ.get("API_ID", 31943015))
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")
OWNER_ID = int(environ.get("OWNER_ID", "8512604416")) 

DB_PATH = "bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS sudos (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY)")
        # Add owner to sudo by default
        await db.execute("INSERT OR IGNORE INTO sudos VALUES (?)", (OWNER_ID,))
        await db.commit()

# Helper functions for DB
async def is_sudo(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM sudos WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def is_auth_chat(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM chats WHERE chat_id = ?", (chat_id,)) as cursor:
            return await cursor.fetchone() is not None

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# =========================
# 🛠 SUDO & CHAT MANAGEMENT
# =========================

@app.on_message(filters.command("addsudo") & filters.user(OWNER_ID))
async def add_sudo_handler(_, message):
    if len(message.command) < 2: return await message.reply("Give me a User ID.")
    uid = int(message.command[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO sudos VALUES (?)", (uid,))
        await db.commit()
    await message.reply(f"✅ User `{uid}` added to Sudo.")

@app.on_message(filters.command("addchat") & filters.private)
async def add_chat_handler(_, message):
    if not await is_sudo(message.from_user.id): return
    if len(message.command) < 2: return await message.reply("Give me a Chat ID.")
    cid = int(message.command[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO chats VALUES (?)", (cid,))
        await db.commit()
    await message.reply(f"✅ Chat `{cid}` authorized.")

# =========================
# 🚫 REMOVE ALL (WITH CONFIRM)
# =========================

@app.on_message(filters.command(["remove_all", "banall"]) & (filters.group | filters.channel))
async def confirm_remove(client, message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # 1. Security Check
    if not await is_sudo(user_id):
        return await message.reply("❌ **Unauthorized.** You are not a Sudo user.")
    
    if not await is_auth_chat(chat_id):
        return await message.reply("❌ This group is not in my authorized list. Use `/addchat` in PM.")

    # 2. Permission Check
    bot = await client.get_chat_member(chat_id, "me")
    if not bot.privileges or not bot.privileges.can_restrict_members:
        return await message.reply("🚨 I need 'Ban Users' permission!")

    # 3. Confirmation UI
    buttons = Markup([[
        Button("✅ Yes, Clean it", callback_data=f"execute_clean|{user_id}"),
        Button("❌ Cancel", callback_data=f"cancel_clean|{user_id}")
    ]])
    
    await message.reply(
        "⚠️ **WARNING**\n\nThis will remove ALL members from this group (except Admins).\nAre you absolutely sure?",
        reply_markup=buttons
    )

@app.on_callback_query(filters.regex(r"^(execute_clean|cancel_clean)\|(\d+)"))
async def handle_callback(client, callback_query: CallbackQuery):
    action, owner_id = callback_query.data.split("|")
    
    if callback_query.from_user.id != int(owner_id):
        return await callback_query.answer("Not your button!", show_alert=True)

    if action == "cancel_clean":
        return await callback_query.edit_message_text("❌ Operation cancelled.")

    # Start the cleaning process
    await callback_query.edit_message_text("🔄 Initializing... Members will be removed shortly.")
    
    chat_id = callback_query.message.chat.id
    count = 0
    
    async for member in client.get_chat_members(chat_id):
        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            continue # Admin protection

        try:
            await client.ban_chat_member(chat_id, member.user.id)
            count += 1
            if count % 15 == 0: # Update every 15 for speed/rate limits
                await callback_query.edit_message_text(f"🚀 **Cleaning in Progress**\n\n✅ Removed: `{count}`")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            continue

    await callback_query.edit_message_text(f"🎉 **Task Finished!**\n\nTotal Members Cleared: `{count}`")

# =========================
# 🚀 STARTUP
# =========================

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    print("Database Ready. Bot Starting...")
    app.run()
