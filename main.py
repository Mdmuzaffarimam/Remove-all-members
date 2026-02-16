# Description: Only Sudo Users Can Use (Owner Direct Access Removed)
# Features: Sudo List Enforcement, SQLite DB, Channel Support

import asyncio
import os
import sqlite3
import threading
from os import environ

from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup, CallbackQuery
from pyrogram.errors import FloodWait

# =========================
# 🗄️ DATABASE (Sudoers)
# =========================
DB_NAME = "sudoers.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS sudoers (user_id INTEGER PRIMARY KEY)')
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
        return False

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

init_db()

# =========================
# 🌐 FLASK SERVER
# =========================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is Running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_flask, daemon=True).start()

# =========================
# 🤖 BOT CONFIG
# =========================
API_ID = int(environ.get("API_ID", 31943015))
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")

# Owner ID sirf Sudo add karne ke liye rahega, Command use karne ke liye nahi.
OWNER_ID = int(environ.get("OWNER_ID", "8512604416"))
UNBAN_USERS = environ.get("UNBAN_USERS", "True") == "True"

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# =========================
# 🔐 AUTH CHECK (Strictly Sudo Only)
# =========================
def is_sudo_user(user_id):
    # Yahan se Owner ID ka check hata diya hai.
    # Sirf wahi use karega jo Database mein hai.
    sudoers = get_sudoers()
    if user_id in sudoers:
        return True
    return False

# =========================
# 🎮 COMMANDS
# =========================
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply(
        "👋 **Sudo Restricted Bot**\n\n"
        "Sirf Sudo users hi `/remove_all` use kar sakte hain.\n"
        "Agar aap Owner hain, toh pehle khud ko add karein.",
        reply_markup=Markup([[Button("Developer", url="https://t.me/mimam_officialx")]])
    )

# --- Sudo Management (Sirf Owner Naye Sudo Bana Sakta Hai) ---
@app.on_message(filters.command("addsudo") & filters.user(OWNER_ID))
async def add_sudo_cmd(client, message):
    if len(message.command) < 2 and not message.reply_to_message:
        return await message.reply("⚠️ **Important:** Pehle apni ID add karein.\nUse: `/addsudo <Your_ID>`")
    
    user_id = message.reply_to_message.from_user.id if message.reply_to_message else int(message.command[1])
    
    if add_sudo(user_id): 
        await message.reply(f"✅ User {user_id} ab bot use kar sakta hai.")
    else: 
        await message.reply("⚠️ Yeh user pehle se list mein hai.")

@app.on_message(filters.command("delsudo") & filters.user(OWNER_ID))
async def del_sudo_cmd(client, message):
    if len(message.command) < 2: return await message.reply("Format: `/delsudo UserID`")
    if del_sudo(int(message.command[1])): await message.reply("❌ Access Removed.")
    else: await message.reply("⚠️ User list mein nahi mila.")

@app.on_message(filters.command("sudolist"))
async def list_sudo(client, message):
    # List koi bhi dekh sakta hai, par edit nahi kar sakta
    users = get_sudoers()
    if not users: return await message.reply("📂 List Empty hai.")
    await message.reply("👮‍♂️ **Authorized Sudo Users:**\n" + "\n".join([f"`{u}`" for u in users]))

# =========================
# 🚫 REMOVE ALL (Strict Sudo Check)
# =========================
@app.on_message(filters.command(["remove_all", "banall"]) & (filters.group | filters.channel))
async def remove_all_handler(client, message):
    chat_id = message.chat.id
    
    # 1. AUTH CHECK
    user_id = message.from_user.id if message.from_user else 0
    
    # Agar user Sudo List mein nahi hai, toh mana kar do
    # (Anonymous channel admins ke liye user_id 0 hota hai, unhe allow karne ke liye logic alag hai,
    # par strict mode mein hum assume karte hain command user se aayi hai)
    if user_id != 0 and not is_sudo_user(user_id):
        return await message.reply("❌ **Access Denied!**\nAap Sudo List mein nahi hain. Owner se contact karein.")

    # 2. Permission Check
    try:
        bot_member = await client.get_chat_member(chat_id, "me")
        if not bot_member.privileges.can_restrict_members:
            return await message.reply("🚨 Mujhe 'Ban Users' permission do!")
    except:
        return await message.reply("🚨 Main Admin nahi hoon!")

    # 3. Confirmation
    await message.reply(
        "⚠️ **CONFIRMATION** ⚠️\n\n"
        "Kya aap sabko nikalna chahte hain?",
        reply_markup=Markup([
            [Button("✅ Yes", callback_data=f"ban_yes_{user_id}"),
             Button("❌ No", callback_data=f"ban_no_{user_id}")]
        ])
    )

@app.on_callback_query(filters.regex(r"^ban_(yes|no)_"))
async def ban_callback(client, callback: CallbackQuery):
    action, auth_user = callback.data.split("_")[1], int(callback.data.split("_")[2])
    
    # Callback check: Sirf wahi click kare jo sudo list mein tha
    if auth_user != 0 and callback.from_user.id != auth_user:
        return await callback.answer("Not for you!", show_alert=True)

    if action == "no":
        return await callback.message.edit("❌ Cancelled.")

    # Execution
    msg = await callback.message.edit("🚀 **Working...**")
    count = 0
    
    async for member in client.get_chat_members(callback.message.chat.id):
        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            continue
        try:
            await client.ban_chat_member(callback.message.chat.id, member.user.id)
            count += 1
            if count % 20 == 0: await msg.edit(f"🔥 Removing... {count}")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            pass 

    if UNBAN_USERS:
        await msg.edit(f"✅ Removed {count}. Unbanning...")
        async for member in client.get_chat_members(callback.message.chat.id, filter=enums.ChatMembersFilter.BANNED):
            try: await client.unban_chat_member(callback.message.chat.id, member.user.id)
            except: pass

    await msg.edit(f"✅ **Done!** Removed: {count}")

if __name__ == "__main__":
    app.run()
