# Description: Telegram Bot to remove members with Sudo support.
# Fixed: AttributeError 'NoneType' in Channels
# Modified by Gemini for Muzaffar

import asyncio
import os
import threading
from os import environ
from datetime import datetime

from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from pyrogram.errors import FloodWait, RPCError

# Step 3.1: Import sudo functions
try:
    from sudo import init_db, add_sudo, del_sudo, get_all_sudo, is_sudo
except ImportError:
    # Agar sudo.py nahi hai toh error na aaye isliye dummy functions
    def init_db(): pass
    def is_sudo(u): return False

# =========================
# 🌐 FLASK WEB SERVER (FOR KOYEB)
# =========================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is alive!", 200

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
ADMIN_ID = int(environ.get("OWNER_ID", "8512604416"))

UNBAN_USERS = environ.get("UNBAN_USERS", "True") == "True"
BAN_CMD = ["remove_all", "removeall", "banall", "ban_all"]

# Step 3.3: Auth function
def is_authorized(user_id: int):
    if user_id == ADMIN_ID:
        return True
    if is_sudo(user_id):
        return True
    return False

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Step 3.2: Initialize DB
init_db()

# =========================
# 📌 COMMANDS SECTION
# =========================

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user = message.from_user
    await message.reply(
        "👋 Hi! I'm a Group Management Bot!\n\n"
        "✨ **Features:**\n"
        "🚫 Remove all members (Sudo only)\n"
        "⚡ Sudo Management",
        reply_markup=Markup([
            [Button("👨‍💻 Developer", url="https://t.me/mimam_officialx"),
             Button("💬 Support", url="https://t.me/MRN_Chat_Group")],
        ]),
        quote=True
    )
    # Admin Notice
    notice = f"🚀 **Bot Started**\n\n👤 Name: {user.first_name}\n🆔 ID: <code>{user.id}</code>"
    try: await client.send_message(chat_id=ADMIN_ID, text=notice, parse_mode=enums.ParseMode.HTML)
    except: pass

@app.on_message(filters.command("addsudo") & filters.private)
async def addsudo_cmd(client, message):
    if message.from_user.id != ADMIN_ID:
        return await message.reply("❌ Only Owner can add sudo users")
    
    user_id = None
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    elif len(message.command) > 1:
        try: user_id = int(message.command[1])
        except: pass

    if not user_id:
        return await message.reply("Usage: /addsudo user_id (or reply to user)")
    
    add_sudo(user_id)
    await message.reply(f"✅ Added {user_id} as Sudo User")

@app.on_message(filters.command("delsudo") & filters.private)
async def delsudo_cmd(client, message):
    if message.from_user.id != ADMIN_ID:
        return await message.reply("❌ Only Owner can remove sudo users")
    
    user_id = None
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    elif len(message.command) > 1:
        try: user_id = int(message.command[1])
        except: pass

    if not user_id:
        return await message.reply("Usage: /delsudo user_id (or reply to user)")
    
    del_sudo(user_id)
    await message.reply(f"🗑 Removed {user_id} from Sudo Users")

@app.on_message(filters.command("sudolist") & filters.private)
async def sudolist_cmd(client, message):
    sudo_users = get_all_sudo()
    text = f"👑 **Owner:**\n<code>{ADMIN_ID}</code>\n\n⚡ **Sudo Users:**\n"
    if not sudo_users: text += "No sudo users added"
    else:
        for user in sudo_users: text += f"• <code>{user}</code>\n"
    await message.reply(text)

# =========================
# 🚫 REMOVE ALL USERS (FIXED)
# =========================
@app.on_message(filters.command(BAN_CMD) & (filters.group | filters.channel))
async def remove_all_users(client, message):
    # 🛠 FIX: Check if message is from a user or channel
    if message.from_user:
        user_id = message.from_user.id
        if not is_authorized(user_id):
            return await message.reply("❌ You are not authorized to use this command")
    elif message.sender_chat:
        # Agar channel se command aayi hai, toh check karein ki wo wahi channel hai jiska bot admin hai
        pass 
    else:
        return # Unknown sender type

    chat_id = message.chat.id
    
    # Check Bot Permissions
    try:
        bot_admin = await client.get_chat_member(chat_id, "me")
        if not bot_admin.privileges or not bot_admin.privileges.can_restrict_members:
            await message.reply("🚨 I need 'Ban Users' permission to work here!")
            return
    except Exception:
        await message.reply("❌ I am not an admin in this chat!")
        return

    count = 0
    update_message = await message.reply("🔄 **Process Started...**\n⌛ Removing members...", quote=True)

    async for member in client.get_chat_members(chat_id):
        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            continue
        try:
            await client.ban_chat_member(chat_id, member.user.id)
            count += 1
            if count % 10 == 0:
                try: await update_message.edit(f"✅ Members removed: {count}")
                except: pass
        except FloodWait as e: await asyncio.sleep(e.value)
        except RPCError: pass

    if UNBAN_USERS:
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            try: await client.unban_chat_member(chat_id, member.user.id)
            except FloodWait as e: await asyncio.sleep(e.value)
            except RPCError: pass

    await update_message.edit(f"🎉 **Operation Complete!**\n\n👥 Total Members Removed: {count}")

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
