# Description: Advanced Group Cleaner Bot with Sudo & DB
# By: MrTamilKiD
# Updates: "For more updates join @KR_BotX"
# Modified: Added Sudo, DB, Confirmation, Admin Protection

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

# Initialise DB on start
init_db()

# =========================
# 🌐 FLASK WEB SERVER
# =========================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is alive and Database is running!", 200

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

# Unban users after removing (kick logic) or just Ban?
# True = Ban then Unban (Kick) | False = Ban only
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
# 📌 START & HELP
# =========================
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user = message.from_user
    await message.reply(
        "👋 **Advanced Group Cleaner Bot**\n\n"
        "I can remove all members from a group with safety checks.\n\n"
        "**Commands:**\n"
        "🔹 `/remove_all` - Remove members (Group only)\n"
        "🔹 `/addsudo <id>` - Add admin (Owner only)\n"
        "🔹 `/delsudo <id>` - Remove admin (Owner only)\n"
        "🔹 `/sudolist` - View admins",
        reply_markup=Markup([
            [Button("👨‍💻 Developer", url="https://t.me/mimam_officialx")],
            [Button("⭐ Source Code", url="https://papajiurl.com/rryy3p")]
        ])
    )

# =========================
# 👤 SUDO COMMANDS (Runtime)
# =========================
@app.on_message(filters.command("addsudo") & filters.user(OWNER_ID))
async def add_sudo_user(client, message):
    if len(message.command) < 2 and not message.reply_to_message:
        return await message.reply("Usage: `/addsudo <user_id>` or reply to user.")
    
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    else:
        try:
            user_id = int(message.command[1])
        except ValueError:
            return await message.reply("Invalid User ID.")

    if add_sudo(user_id):
        await message.reply(f"✅ Added {user_id} to Sudo list.")
    else:
        await message.reply("⚠️ User is already in Sudo list.")

@app.on_message(filters.command("delsudo") & filters.user(OWNER_ID))
async def del_sudo_user(client, message):
    if len(message.command) < 2:
        return await message.reply("Usage: `/delsudo <user_id>`")
    
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply("Invalid User ID.")

    if del_sudo(user_id):
        await message.reply(f"❌ Removed {user_id} from Sudo list.")
    else:
        await message.reply("⚠️ User not found in Sudo list.")

@app.on_message(filters.command("sudolist") & filters.user(OWNER_ID))
async def list_sudo(client, message):
    users = get_sudoers()
    if not users:
        return await message.reply("📂 Sudo list is empty.")
    text = "👮‍♂️ **Sudo Users:**\n\n" + "\n".join([f"🆔 `{uid}`" for uid in users])
    await message.reply(text)

# =========================
# 🚫 BAN ALL LOGIC
# =========================
@app.on_message(filters.command(["remove_all", "banall"]) & filters.group)
async def request_ban_all(client, message):
    user_id = message.from_user.id
    
    # 1. Check Authorization
    if not await is_authorized(user_id):
        return await message.reply("❌ **Access Denied!** You are not an authorized admin.")

    # 2. Check Bot Permissions
    chat_id = message.chat.id
    bot_member = await client.get_chat_member(chat_id, "me")
    if not bot_member.privileges or not bot_member.privileges.can_restrict_members:
        return await message.reply("🚨 I need 'Ban Users' permission first!")

    # 3. Confirmation Buttons
    confirm_btn = Markup([
        [
            Button("✅ Yes, Do it", callback_data=f"ban_yes_{user_id}"),
            Button("❌ Cancel", callback_data=f"ban_no_{user_id}")
        ]
    ])
    
    await message.reply(
        "⚠️ **WARNING** ⚠️\n\n"
        "Are you sure you want to remove **ALL** members from this group?\n"
        "This action cannot be undone instantly.",
        reply_markup=confirm_btn
    )

@app.on_callback_query(filters.regex(r"^ban_(yes|no)_"))
async def ban_callback(client, callback: CallbackQuery):
    data = callback.data.split("_")
    action = data[1]
    auth_user = int(data[2])

    if callback.from_user.id != auth_user:
        return await callback.answer("❌ Not for you!", show_alert=True)

    if action == "no":
        await callback.message.edit("❌ Operation Cancelled.")
        return

    # START BANNING PROCESS
    chat_id = callback.message.chat.id
    await callback.message.edit("🔄 **Initializing Mass Ban...**\n\n🛡️ Admin Protection: ON")
    
    count = 0
    errors = 0
    
    msg = callback.message
    
    async for member in client.get_chat_members(chat_id):
        # 4. Admin Protection
        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            continue
            
        try:
            await client.ban_chat_member(chat_id, member.user.id)
            count += 1
            
            # 5. Progress Update (Every 20 users to avoid floodwait on edits)
            if count % 20 == 0:
                try:
                    await msg.edit(f"🔄 **Cleaning Group...**\n\n🗑️ Removed: {count}\n⚠️ Errors: {errors}")
                except:
                    pass
            
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            errors += 1
            pass

    # Optional: Unban logic (Clean list)
    if UNBAN_USERS:
        await msg.edit(f"✅ Removal done ({count}). Now unbanning to clear blocklist...")
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            try:
                await client.unban_chat_member(chat_id, member.user.id)
            except:
                pass

    await msg.edit(
        f"🎉 **Operation Completed!**\n\n"
        f"👤 Users Removed: {count}\n"
        f"🛡️ Admins Saved: All safe"
    )

# =========================
# 🚀 RUN BOT
# =========================
if __name__ == "__main__":
    print("Bot + Web Server + DB running...")
    app.run()
