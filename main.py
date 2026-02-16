# Description: Chat ID Based Auth (No User Limit)
# Features: Whitelist Groups/Channels, Admin Check
# By: MrTamilKiD

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
# 🗄️ DATABASE (Allowed Chats)
# =========================
DB_NAME = "allowed_chats.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY)')
    conn.commit()
    conn.close()

def add_chat_db(chat_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO chats (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

def del_chat_db(chat_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
    changes = conn.total_changes
    conn.commit()
    conn.close()
    return changes > 0

def get_allowed_chats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM chats")
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
    return "Bot is Running (Chat ID Auth Mode)!", 200

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
OWNER_ID = int(environ.get("OWNER_ID", "8512604416"))
UNBAN_USERS = environ.get("UNBAN_USERS", "True") == "True"

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# =========================
# 🔐 AUTH CHECK (Chat ID Logic)
# =========================
def is_chat_allowed(chat_id):
    # Check karega ki yeh Group/Channel database mein hai ya nahi
    allowed = get_allowed_chats()
    if chat_id in allowed:
        return True
    return False

# =========================
# 🎮 OWNER COMMANDS (Add/Remove Chats)
# =========================
@app.on_message(filters.command("add") & filters.user(OWNER_ID))
async def add_chat_cmd(client, message):
    # Ya toh current chat add karo, ya command ke saath ID do
    # Usage: /add (in group) OR /add -100123456789 (in private)
    
    if len(message.command) > 1:
        try:
            target_id = int(message.command[1])
        except:
            return await message.reply("❌ Invalid ID format.")
    else:
        target_id = message.chat.id

    if add_chat_db(target_id):
        await message.reply(f"✅ **Authorized!**\nChat ID `{target_id}` ab allowed hai.")
    else:
        await message.reply(f"⚠️ Chat ID `{target_id}` pehle se allowed hai.")

@app.on_message(filters.command("remove") & filters.user(OWNER_ID))
async def del_chat_cmd(client, message):
    if len(message.command) > 1:
        try:
            target_id = int(message.command[1])
        except:
            return await message.reply("❌ Invalid ID format.")
    else:
        target_id = message.chat.id

    if del_chat_db(target_id):
        await message.reply(f"❌ **Removed!**\nChat ID `{target_id}` ab use nahi kar payega.")
    else:
        await message.reply("⚠️ Yeh ID list mein nahi mili.")

@app.on_message(filters.command("list") & filters.user(OWNER_ID))
async def list_chats(client, message):
    chats = get_allowed_chats()
    if not chats: return await message.reply("📂 No authorized chats.")
    
    text = "📋 **Authorized Chats:**\n\n"
    for cid in chats:
        text += f"🆔 `{cid}`\n"
    await message.reply(text)

# =========================
# 🚫 BAN ALL LOGIC (Chat ID + Local Admin)
# =========================
@app.on_message(filters.command(["remove_all", "banall"]) & (filters.group | filters.channel))
async def remove_all_handler(client, message):
    chat_id = message.chat.id
    
    # 1. CHAT AUTHORIZATION CHECK (Database)
    if not is_chat_allowed(chat_id):
        return await message.reply(
            f"❌ **Access Denied!**\n"
            f"Yeh Chat (ID: `{chat_id}`) authorized nahi hai.\n"
            f"Owner se contact karke ID add karwayein."
        )

    # 2. ADMIN CHECK (Sirf Group ke liye)
    # Channel mein toh sirf admin hi post kar sakta hai, toh check ki zaroorat nahi.
    # Group mein check karna padega ki command dene wala Group Admin hai ya nahi.
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        member = await client.get_chat_member(chat_id, message.from_user.id)
        if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
             return await message.reply("❌ **Access Denied!**\nAap is Group ke Admin nahi hain.")

    # 3. BOT PERMISSION CHECK
    try:
        bot = await client.get_chat_member(chat_id, "me")
        if not bot.privileges.can_restrict_members:
            return await message.reply("🚨 Mujhe 'Ban Users' permission do!")
    except:
        return await message.reply("🚨 Main Admin nahi hoon!")

    # 4. CONFIRMATION
    # Channel posts ke liye user_id 0 set karenge
    user_id = message.from_user.id if message.from_user else 0
    
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
    
    # Verification: Sirf wahi dabaye jisne command di (Channel mein skip)
    if auth_user != 0 and callback.from_user.id != auth_user:
        return await callback.answer("Not for you!", show_alert=True)

    if action == "no":
        return await callback.message.edit("❌ Cancelled.")

    # START CLEANING
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
