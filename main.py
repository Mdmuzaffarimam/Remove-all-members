# Description: Ultimate Group/Channel Cleaner Bot
# Features: Sudo, SQLite DB, Safety Checks, Channel Support
# By: MrTamilKiD
# Modified for: MRN Channel

import asyncio
import os
import sqlite3
import threading
from os import environ
from datetime import datetime

from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup, CallbackQuery
from pyrogram.errors import FloodWait, RPCError

# =========================
# 🗄️ DATABASE MANAGEMENT (SQLite)
# =========================
DB_NAME = "sudoers.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sudoers (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def add_sudo(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sudoers (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False  # Already exists

def del_sudo(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sudoers WHERE user_id = ?", (user_id,))
    changes = conn.total_changes
    conn.commit()
    conn.close()
    return changes > 0

def get_sudoers():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM sudoers")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

# Initialize DB
init_db()

# =========================
# 🌐 FLASK WEB SERVER (Keep Alive)
# =========================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running fine!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_flask, daemon=True).start()

# =========================
# 🤖 TELEGRAM BOT CONFIG
# =========================
API_ID = int(environ.get("API_ID", 31943015))
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")

OWNER_ID = int(environ.get("OWNER_ID", "8512604416"))

# Set to True to Unban users after removing (Clean List)
UNBAN_USERS = environ.get("UNBAN_USERS", "True") == "True"

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# =========================
# 🔐 AUTH HELPER
# =========================
async def is_authorized(user_id):
    if user_id == OWNER_ID:
        return True
    if user_id in get_sudoers():
        return True
    return False

# =========================
# 📌 START & SUDO COMMANDS
# =========================
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply(
        "👋 **Ultimate Cleaner Bot**\n\n"
        "Works in Groups & Channels!\n\n"
        "**Commands:**\n"
        "🗑️ `/remove_all` - Remove everyone\n"
        "👤 `/addsudo <id>` - Add Admin\n"
        "🚫 `/delsudo <id>` - Remove Admin\n"
        "📝 `/sudolist` - View Admins",
        reply_markup=Markup([
            [Button("👨‍💻 Developer", url="https://t.me/mimam_officialx")]
        ])
    )

@app.on_message(filters.command("addsudo") & filters.user(OWNER_ID))
async def add_sudo_user(client, message):
    if len(message.command) < 2 and not message.reply_to_message:
        return await message.reply("Usage: `/addsudo <user_id>` or Reply to user")
    
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    else:
        try:
            user_id = int(message.command[1])
        except:
            return await message.reply("Invalid ID")

    if add_sudo(user_id):
        await message.reply(f"✅ Added {user_id} to Sudo.")
    else:
        await message.reply("⚠️ Already in list.")

@app.on_message(filters.command("delsudo") & filters.user(OWNER_ID))
async def del_sudo_user(client, message):
    if len(message.command) < 2:
        return await message.reply("Usage: `/delsudo <user_id>`")
    
    try:
        user_id = int(message.command[1])
        if del_sudo(user_id):
            await message.reply(f"❌ Removed {user_id}.")
        else:
            await message.reply("⚠️ Not found.")
    except:
        await message.reply("Invalid ID")

@app.on_message(filters.command("sudolist") & filters.user(OWNER_ID))
async def list_sudo(client, message):
    users = get_sudoers()
    if not users:
        return await message.reply("📂 List empty.")
    await message.reply("👮‍♂️ **Sudoers:**\n" + "\n".join([f"`{u}`" for u in users]))

# =========================
# 🚫 BAN LOGIC (Groups + Channels)
# =========================
@app.on_message(filters.command(["remove_all", "banall"]) & (filters.group | filters.channel))
async def request_ban_all(client, message):
    chat_id = message.chat.id
    
    # 1. Authorization Check
    # If it's a normal user/group message
    if message.from_user:
        user_id = message.from_user.id
        if not await is_authorized(user_id):
            return await message.reply("❌ **Access Denied!**")
    
    # If it's an Anonymous Admin or Channel Post (from_user is None)
    # Telegram ensures only admins can post in channels, so we proceed.
    else:
        user_id = 0 

    # 2. Permission Check
    bot = await client.get_chat_member(chat_id, "me")
    if not bot.privileges or not bot.privileges.can_restrict_members:
        return await message.reply("🚨 I need 'Ban Users' permission!")

    # 3. Confirmation
    confirm_btn = Markup([
        [
            Button("✅ Yes, Clean It", callback_data=f"ban_yes_{user_id}"),
            Button("❌ Cancel", callback_data=f"ban_no_{user_id}")
        ]
    ])
    
    await message.reply(
        "⚠️ **WARNING** ⚠️\n\n"
        "Are you sure you want to remove **ALL** members?\n"
        "Admins will be saved.",
        reply_markup=confirm_btn
    )

@app.on_callback_query(filters.regex(r"^ban_(yes|no)_"))
async def ban_callback(client, callback: CallbackQuery):
    data = callback.data.split("_")
    action = data[1]
    auth_user = int(data[2])

    # Verify User (if not anonymous channel admin)
    if auth_user != 0 and callback.from_user.id != auth_user:
        return await callback.answer("❌ Not for you!", show_alert=True)

    if action == "no":
        await callback.message.edit("❌ Cancelled.")
        return

    # START PROCESS
    chat_id = callback.message.chat.id
    msg = await callback.message.edit("🔄 **Processing...**\n🛡️ Admins are safe.")
    
    count = 0
    errors = 0
    
    # Fetch members
    async for member in client.get_chat_members(chat_id):
        # Skip Admins & Bots
        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            continue
        
        try:
            await client.ban_chat_member(chat_id, member.user.id)
            count += 1
            
            # Update status every 20 users
            if count % 20 == 0:
                try:
                    await msg.edit(f"🔄 **Removing...**\n🗑️ Gone: {count}")
                except:
                    pass
                    
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            errors += 1

    # UNBAN LOOP (To clear Blocklist)
    if UNBAN_USERS:
        await msg.edit(f"✅ Banned {count}. Now unbanning...")
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            try:
                await client.unban_chat_member(chat_id, member.user.id)
            except:
                pass

    await msg.edit(
        f"🎉 **Clean Complete!**\n\n"
        f"👤 Removed: {count}\n"
        f"⚠️ Failed: {errors}"
    )

# =========================
# 🚀 RUN
# =========================
if __name__ == "__main__":
    print("Bot Started...")
    app.run()
