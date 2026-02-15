import asyncio
import os
import sqlite3
import threading
from os import environ

from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup, CallbackQuery
from pyrogram.errors import FloodWait, RPCError

# =========================
# 🗄️ DATABASE (Admins Save Karne Ke Liye)
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
# 🌐 WEB SERVER (Bot Ko Online Rakhne Ke Liye)
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
# 🤖 BOT CONFIGURATION
# =========================
API_ID = int(environ.get("API_ID", 0)) # Yahan apna API ID daalna agar hardcode karna ho
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")
OWNER_ID = int(environ.get("OWNER_ID", "0"))

# True = Ban karke Unban karega (List saaf karega)
UNBAN_USERS = environ.get("UNBAN_USERS", "True") == "True"

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# =========================
# 🛠️ HELPER FUNCTIONS
# =========================
async def is_authorized(user_id):
    if user_id == OWNER_ID:
        return True
    if user_id in get_sudoers():
        return True
    return False

# =========================
# 🎮 COMMANDS
# =========================
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply(
        "👋 **Bot Online Hai!**\n\n"
        "Main Groups aur Channels se sabko remove kar sakta hoon.\n\n"
        "🛠 **Commands:**\n"
        "`/remove_all` - Sabko nikalne ke liye\n"
        "`/addsudo` - Admin banane ke liye (Owner only)",
        reply_markup=Markup([[Button("Developer", url="https://t.me/mimam_officialx")]])
    )

# --- Sudo Add/Remove ---
@app.on_message(filters.command("addsudo") & filters.user(OWNER_ID))
async def add_sudo_cmd(client, message):
    if len(message.command) < 2 and not message.reply_to_message:
        return await message.reply("Format: `/addsudo UserID` ya reply karo.")
    user_id = message.reply_to_message.from_user.id if message.reply_to_message else int(message.command[1])
    if add_sudo(user_id): await message.reply("✅ Admin Added.")
    else: await message.reply("⚠️ Already Admin.")

@app.on_message(filters.command("delsudo") & filters.user(OWNER_ID))
async def del_sudo_cmd(client, message):
    if len(message.command) < 2: return await message.reply("Format: `/delsudo UserID`")
    if del_sudo(int(message.command[1])): await message.reply("❌ Admin Removed.")
    else: await message.reply("⚠️ Not Found.")

# =========================
# 🚫 REMOVE ALL (MAIN LOGIC)
# =========================
@app.on_message(filters.command(["remove_all", "banall", "kickall"]) & (filters.group | filters.channel))
async def remove_all_handler(client, message):
    chat_id = message.chat.id
    
    # 1. Permission Check (Bot Admin Hai Ya Nahi?)
    try:
        bot_member = await client.get_chat_member(chat_id, "me")
        if not bot_member.privileges.can_restrict_members:
            return await message.reply("🚨 Mujhe 'Ban Users' ki permission do pehle!")
    except Exception as e:
        return await message.reply(f"🚨 Error: Main shayad admin nahi hoon. ({e})")

    # 2. Authorization Check (Kaun command de raha hai?)
    if message.from_user:
        # Group msg ya Private Channel msg
        if not await is_authorized(message.from_user.id):
            return await message.reply("❌ Aap Owner ya Sudo admin nahi ho.")
        user_id = message.from_user.id
    else:
        # Anonymous Channel Post (Channel mein sirf admin hi post kar sakta hai)
        # Isliye hum isse allow karenge lekin confirmation ID 0 rakhenge
        user_id = 0

    # 3. Confirmation Button
    await message.reply(
        "⚠️ **WARNING: SABKO NIKAL DU?** ⚠️\n\n"
        "Isse undo nahi kiya ja sakta.",
        reply_markup=Markup([
            [Button("✅ Yes, Remove All", callback_data=f"ban_yes_{user_id}"),
             Button("❌ Cancel", callback_data=f"ban_no_{user_id}")]
        ])
    )

# --- Callback Handler (Button Click) ---
@app.on_callback_query(filters.regex(r"^ban_(yes|no)_"))
async def ban_callback(client, callback: CallbackQuery):
    action, auth_user = callback.data.split("_")[1], int(callback.data.split("_")[2])
    
    # Security: Sirf wahi click kare jisne command di (Channel ke liye skip)
    if auth_user != 0 and callback.from_user.id != auth_user:
        return await callback.answer("Yeh button tumhare liye nahi hai!", show_alert=True)

    if action == "no":
        return await callback.message.edit("❌ Cancelled.")

    # START CLEANING
    chat_id = callback.message.chat.id
    msg = await callback.message.edit("🚀 **Kaam shuru kar raha hoon...**")
    
    count = 0
    
    # Members Loop
    async for member in client.get_chat_members(chat_id):
        # Admins aur Bots ko skip karo
        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            continue
        
        try:
            await client.ban_chat_member(chat_id, member.user.id)
            count += 1
            if count % 20 == 0:
                await msg.edit(f"🔥 Removing... {count} done.")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            pass 

    # Unban (Optional)
    if UNBAN_USERS:
        await msg.edit(f"✅ {count} removed. Ab unban kar raha hoon (List saaf karne ke liye)...")
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            try:
                await client.unban_chat_member(chat_id, member.user.id)
            except: pass

    await msg.edit(f"✅ **Mission Complete!**\n🗑 Total Removed: {count}")

if __name__ == "__main__":
    app.run()
