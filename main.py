# Description: Final Fixed Bot (Start Image, DB Lock Fix, Chat ID Auth, Auto-Schedule)
# Features: Thread-safe DB, Whitelist Logic, Start Photo, Flask Keep-Alive, Scheduled Remove
# By: MrTamilKiD

import asyncio
import os
import sqlite3
import threading
from datetime import datetime
from os import environ

from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup, CallbackQuery
from pyrogram.errors import FloodWait

# =========================
# 🖼️ CONFIGURATION
# =========================
START_IMG_URL = "https://files.catbox.moe/5wxw6n.jpg"

API_ID = int(environ.get("API_ID", 31943015))
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")
OWNER_ID = int(environ.get("OWNER_ID", "6139759254"))
UNBAN_USERS = environ.get("UNBAN_USERS", "True") == "True"

# =========================
# 🗄️ DATABASE WITH LOCK
# =========================
DB_NAME = "allowed_chats.db"
DB_LOCK = threading.Lock()

def init_db():
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY)')
        # ✅ NEW: Schedule table — stores chat_id + time (HH:MM)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                chat_id INTEGER PRIMARY KEY,
                schedule_time TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

def add_chat_db(chat_id):
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DB_NAME, check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO chats (chat_id) VALUES (?)", (chat_id,))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            return False

def del_chat_db(chat_id):
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
        changes = conn.total_changes
        conn.commit()
        conn.close()
        return changes > 0

def get_allowed_chats():
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM chats")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]

# ✅ NEW: Schedule DB functions
def set_schedule(chat_id, time_str):
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO schedules (chat_id, schedule_time) VALUES (?, ?)",
            (chat_id, time_str)
        )
        conn.commit()
        conn.close()

def del_schedule(chat_id):
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM schedules WHERE chat_id = ?", (chat_id,))
        changes = conn.total_changes
        conn.commit()
        conn.close()
        return changes > 0

def get_all_schedules():
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id, schedule_time FROM schedules")
        rows = cursor.fetchall()
        conn.close()
        return rows  # list of (chat_id, "HH:MM")

def get_schedule(chat_id):
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT schedule_time FROM schedules WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

init_db()

# =========================
# 🌐 FLASK SERVER
# =========================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is Running Securely!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_flask, daemon=True).start()

# =========================
# 🤖 BOT CLIENT
# =========================
app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# =========================
# 🔐 AUTH CHECK
# =========================
def is_chat_allowed(chat_id):
    return chat_id in get_allowed_chats()

# =========================
# ⏰ SCHEDULER LOOP (Background Task)
# =========================
async def scheduler_loop():
    """Runs every minute, checks if any scheduled remove_all is due."""
    await asyncio.sleep(10)  # Wait for bot to fully start
    while True:
        now = datetime.now().strftime("%H:%M")
        schedules = get_all_schedules()
        for chat_id, sched_time in schedules:
            if sched_time == now:
                print(f"[SCHEDULER] Triggering remove_all for chat {chat_id} at {now}")
                try:
                    await do_remove_all(app, chat_id)
                except Exception as e:
                    print(f"[SCHEDULER ERROR] {chat_id}: {e}")
        await asyncio.sleep(60)  # Check every 60 seconds

# =========================
# 🚀 CORE: DO REMOVE ALL (Reusable function)
# =========================
async def do_remove_all(client, chat_id, status_chat_id=None):
    """
    Removes all non-admin members from chat_id.
    status_chat_id: send progress messages here (defaults to chat_id).
    """
    if status_chat_id is None:
        status_chat_id = chat_id

    try:
        msg = await client.send_message(status_chat_id, "🚀 **Auto-Remove Started...**\n🛡️ Admins are safe.")
    except Exception:
        msg = None

    count = 0
    async for member in client.get_chat_members(chat_id):
        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            continue
        try:
            await client.ban_chat_member(chat_id, member.user.id)
            count += 1
            if count % 20 == 0 and msg:
                await msg.edit(f"🔥 Removing... {count}")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            pass

    if UNBAN_USERS:
        if msg:
            await msg.edit(f"✅ Removed {count}. Unbanning to clear blocked list...")
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            try:
                await client.unban_chat_member(chat_id, member.user.id)
            except:
                pass

    if msg:
        await msg.edit(f"✅ **Clean Complete!**\n🗑 Total Removed: **{count}**")

# =========================
# 📌 START COMMAND
# =========================
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_photo(
        photo=START_IMG_URL,
        caption=(
            "👋 **Hi! I'm the Ultimate Group/Channel Cleaner Bot.**\n\n"
            "I can remove all members from whitelisted groups and channels.\n\n"
            "**👑 For Owner:**\n"
            "🔹 `/add` — Add current group/channel to whitelist.\n"
            "🔹 `/remove` — Remove from whitelist.\n"
            "🔹 `/list` — See allowed chats.\n\n"
            "**⏰ Schedule Commands (Owner, in whitelisted chat):**\n"
            "🔹 `/schedule 23:00` — Auto-remove daily at 11 PM.\n"
            "🔹 `/schedule cancel` — Cancel schedule.\n"
            "🔹 `/schedule status` — See current schedule.\n\n"
            "**🛡️ For Admins (in whitelisted chats):**\n"
            "🔹 `/remove_all` — Remove all members now."
        ),
        reply_markup=Markup([
            [Button("👨‍💻 Developer", url="https://t.me/mimam_officialx"),
             Button("📢 Updates", url="https://t.me/Mrn_Officialx")]
        ])
    )

# =========================
# 🎮 OWNER COMMANDS
# =========================
@app.on_message(filters.command("add") & filters.user(OWNER_ID))
async def add_chat_cmd(client, message):
    if len(message.command) > 1:
        try:
            target_id = int(message.command[1])
        except:
            return await message.reply("❌ Invalid ID.")
    else:
        target_id = message.chat.id

    if add_chat_db(target_id):
        await message.reply(f"✅ **Authorized!**\nChat ID `{target_id}` added.")
    else:
        await message.reply(f"⚠️ Chat `{target_id}` already authorized.")

@app.on_message(filters.command("remove") & filters.user(OWNER_ID))
async def del_chat_cmd(client, message):
    if len(message.command) > 1:
        try:
            target_id = int(message.command[1])
        except:
            return await message.reply("❌ Invalid ID.")
    else:
        target_id = message.chat.id

    if del_chat_db(target_id):
        await message.reply(f"❌ **Removed!**\nChat ID `{target_id}` deleted.")
    else:
        await message.reply("⚠️ ID not found.")

@app.on_message(filters.command("list") & filters.user(OWNER_ID))
async def list_chats(client, message):
    chats = get_allowed_chats()
    if not chats:
        return await message.reply("📂 No authorized chats.")
    text = "📋 **Allowed Chats:**\n\n" + "\n".join([f"🆔 `{cid}`" for cid in chats])
    await message.reply(text)

# =========================
# ⏰ SCHEDULE COMMAND (NEW)
# =========================
@app.on_message(filters.command("schedule") & filters.user(OWNER_ID) & (filters.group | filters.channel))
async def schedule_cmd(client, message):
    chat_id = message.chat.id

    # Must be whitelisted
    if not is_chat_allowed(chat_id):
        return await message.reply(
            f"❌ **Unauthorized!**\nChat ID `{chat_id}` is not whitelisted.\nUse `/add` first."
        )

    if len(message.command) < 2:
        return await message.reply(
            "⏰ **Schedule Usage:**\n"
            "• `/schedule 23:00` — Set daily auto-remove at 11 PM\n"
            "• `/schedule cancel` — Cancel schedule\n"
            "• `/schedule status` — Check current schedule"
        )

    arg = message.command[1].lower()

    # Cancel
    if arg == "cancel":
        if del_schedule(chat_id):
            return await message.reply("✅ Schedule cancelled for this chat.")
        else:
            return await message.reply("⚠️ No schedule found for this chat.")

    # Status
    if arg == "status":
        t = get_schedule(chat_id)
        if t:
            return await message.reply(f"📅 **Current Schedule:** `{t}` daily")
        else:
            return await message.reply("📭 No schedule set for this chat.")

    # Set time — validate HH:MM format
    try:
        datetime.strptime(arg, "%H:%M")
    except ValueError:
        return await message.reply(
            "❌ **Invalid time format!**\n"
            "Use 24-hour format: `/schedule 23:00` or `/schedule 08:30`"
        )

    set_schedule(chat_id, arg)
    await message.reply(
        f"✅ **Schedule Set!**\n"
        f"⏰ Auto-remove will run daily at **{arg}**\n"
        f"🛡️ Admins will be safe.\n\n"
        f"To cancel: `/schedule cancel`"
    )

# =========================
# 🚫 REMOVE ALL (Manual)
# =========================
@app.on_message(filters.command(["remove_all", "banall"]) & (filters.group | filters.channel))
async def remove_all_handler(client, message):
    chat_id = message.chat.id

    if not is_chat_allowed(chat_id):
        return await message.reply(
            f"❌ **Unauthorized!**\nChat ID `{chat_id}` is not in the whitelist.\n"
            f"Ask Owner to `/add` this chat."
        )

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        member = await client.get_chat_member(chat_id, message.from_user.id)
        if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            return await message.reply("❌ **Access Denied!** You are not an Admin.")

    try:
        bot = await client.get_chat_member(chat_id, "me")
        if not bot.privileges.can_restrict_members:
            return await message.reply("🚨 I need 'Ban Users' permission!")
    except:
        return await message.reply("🚨 I am not Admin!")

    user_id = message.from_user.id if message.from_user else 0
    await message.reply(
        "⚠️ **CONFIRMATION** ⚠️\n\nAre you sure you want to remove **ALL** members? Admins will be saved.",
        reply_markup=Markup([
            [Button("✅ Yes", callback_data=f"ban_yes_{user_id}"),
             Button("❌ No", callback_data=f"ban_no_{user_id}")]
        ])
    )

@app.on_callback_query(filters.regex(r"^ban_(yes|no)_"))
async def ban_callback(client, callback: CallbackQuery):
    action = callback.data.split("_")[1]
    auth_user = int(callback.data.split("_")[2])

    if auth_user != 0 and callback.from_user.id != auth_user:
        return await callback.answer("Not for you!", show_alert=True)

    if action == "no":
        return await callback.message.edit("❌ Cancelled.")

    await callback.message.edit("🚀 **Processing...**")
    await do_remove_all(client, callback.message.chat.id, callback.message.chat.id)

# =========================
# ▶️ RUN
# =========================
async def main():
    async with app:
        # Start scheduler as background task
        asyncio.create_task(scheduler_loop())
        print("Bot Started! Scheduler running...")
        await asyncio.Event().wait()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
