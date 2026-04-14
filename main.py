# Description: Final Fixed Bot (Start Image, DB Lock Fix, Chat ID Auth, Scheduled Remove, Auto-Delete Messages)
# Features: Thread-safe DB, Whitelist Logic, Start Photo, Flask Keep-Alive, Auto Remove Timer, Auto-Delete Messages
# By: MrTamilKiD

import asyncio
import os
import sqlite3
import threading
from datetime import datetime, timedelta
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
        # Scheduled tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                chat_id INTEGER PRIMARY KEY,
                run_at TEXT NOT NULL,
                requested_by INTEGER NOT NULL
            )
        ''')
        # Auto-delete settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS autodelete_settings (
                chat_id INTEGER PRIMARY KEY,
                delay_seconds INTEGER NOT NULL DEFAULT 60,
                enabled INTEGER NOT NULL DEFAULT 0
            )
        ''')
        conn.commit()
        conn.close()

# =========================
# 🗑️ AUTO-DELETE DB FUNCTIONS
# =========================
def set_autodelete(chat_id, delay_seconds, enabled=True):
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO autodelete_settings (chat_id, delay_seconds, enabled) VALUES (?, ?, ?)",
            (chat_id, delay_seconds, 1 if enabled else 0)
        )
        conn.commit()
        conn.close()

def toggle_autodelete(chat_id, enabled: bool):
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO autodelete_settings (chat_id, delay_seconds, enabled) VALUES (?, 60, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET enabled=?",
            (chat_id, 1 if enabled else 0, 1 if enabled else 0)
        )
        conn.commit()
        conn.close()

def get_autodelete(chat_id):
    """Returns (delay_seconds, enabled) or None if not set."""
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT delay_seconds, enabled FROM autodelete_settings WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        conn.close()
        return row  # (delay_seconds, enabled) or None

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

# =========================
# ⏰ SCHEDULER DB FUNCTIONS
# =========================
def add_schedule(chat_id, run_at: datetime, requested_by: int):
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO scheduled_tasks (chat_id, run_at, requested_by) VALUES (?, ?, ?)",
            (chat_id, run_at.isoformat(), requested_by)
        )
        conn.commit()
        conn.close()

def del_schedule(chat_id):
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scheduled_tasks WHERE chat_id = ?", (chat_id,))
        changes = conn.total_changes
        conn.commit()
        conn.close()
        return changes > 0

def get_all_schedules():
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id, run_at, requested_by FROM scheduled_tasks")
        rows = cursor.fetchall()
        conn.close()
        return rows

def get_schedule(chat_id):
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT run_at, requested_by FROM scheduled_tasks WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        conn.close()
        return row

init_db()

# =========================
# ⏱️ IN-MEMORY TASK TRACKER
# =========================
# Stores asyncio.Task objects: { chat_id: asyncio.Task }
active_tasks: dict[int, asyncio.Task] = {}

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
# 🔥 CORE REMOVE LOGIC (reusable)
# =========================
async def do_remove_all(client: Client, chat_id: int, notify_msg=None):
    """Remove all non-admin members from a chat. Optionally edit notify_msg for progress."""
    count = 0
    async for member in client.get_chat_members(chat_id):
        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            continue
        try:
            await client.ban_chat_member(chat_id, member.user.id)
            count += 1
            if notify_msg and count % 20 == 0:
                try:
                    await notify_msg.edit(f"🔥 Removing... {count}")
                except Exception:
                    pass
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            pass

    if UNBAN_USERS:
        if notify_msg:
            try:
                await notify_msg.edit(f"✅ Removed {count}. Unbanning to clear blocked list...")
            except Exception:
                pass
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            try:
                await client.unban_chat_member(chat_id, member.user.id)
            except Exception:
                pass

    return count

# =========================
# ⏰ SCHEDULED TASK RUNNER
# =========================
async def scheduled_remove_task(client: Client, chat_id: int, delay_seconds: float, requested_by: int):
    """Waits for delay, then removes all members and notifies."""
    await asyncio.sleep(delay_seconds)

    # Remove from DB & memory tracker
    del_schedule(chat_id)
    active_tasks.pop(chat_id, None)

    if not is_chat_allowed(chat_id):
        return  # Chat was removed from whitelist before timer fired

    try:
        # Send notification message in group
        msg = await client.send_message(chat_id, "⏰ **Scheduled Remove Started!**\n🛡️ Admins are safe.")
        count = await do_remove_all(client, chat_id, notify_msg=msg)
        await msg.edit(f"✅ **Scheduled Clean Complete!**\n🗑 Total Removed: {count}")
    except Exception as e:
        try:
            await client.send_message(chat_id, f"❌ Scheduled remove failed: {e}")
        except Exception:
            pass

def restore_schedules(client: Client, loop: asyncio.AbstractEventLoop):
    """On bot startup, restore any pending scheduled tasks from DB."""
    rows = get_all_schedules()
    now = datetime.utcnow()
    for chat_id, run_at_str, requested_by in rows:
        run_at = datetime.fromisoformat(run_at_str)
        delay = (run_at - now).total_seconds()
        if delay <= 0:
            # Overdue — run immediately
            delay = 0
        task = loop.create_task(
            scheduled_remove_task(client, chat_id, delay, requested_by)
        )
        active_tasks[chat_id] = task

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
            "🔹 `/add` — Add group to whitelist\n"
            "🔹 `/remove` — Remove from whitelist\n"
            "🔹 `/list` — See allowed chats\n\n"
            "**🛡️ For Admins (in whitelisted chats):**\n"
            "🔹 `/remove_all` — Remove all members now\n"
            "🔹 `/schedule_remove <minutes>` — Auto remove after X mins\n"
            "🔹 `/cancel_remove` — Cancel scheduled remove\n"
            "🔹 `/check_schedule` — See pending timer\n\n"
            "**🗑️ Auto-Delete Messages:**\n"
            "🔹 `/settime <value> [s/m/h]` — Set delete delay\n"
            "🔹 `/gettime` — Show current delay\n"
            "🔹 `/enable` — Enable auto-delete\n"
            "🔹 `/disable` — Disable auto-delete\n"
            "🔹 `/id` — Show chat ID\n\n"
            "Check out the links below!"
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
        except Exception:
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
        except Exception:
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
# ⏰ SCHEDULE REMOVE COMMAND
# =========================
@app.on_message(filters.command("schedule_remove") & (filters.group | filters.channel))
async def schedule_remove_cmd(client, message):
    chat_id = message.chat.id

    # Whitelist check
    if not is_chat_allowed(chat_id):
        return await message.reply(
            f"❌ **Unauthorized!**\nChat ID `{chat_id}` is not whitelisted.\nAsk Owner to `/add` this chat."
        )

    # Admin check
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        member = await client.get_chat_member(chat_id, message.from_user.id)
        if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            return await message.reply("❌ **Access Denied!** You are not an Admin.")

    # Bot permission check
    try:
        bot = await client.get_chat_member(chat_id, "me")
        if not bot.privileges.can_restrict_members:
            return await message.reply("🚨 I need 'Ban Users' permission!")
    except Exception:
        return await message.reply("🚨 I am not Admin here!")

    # Parse minutes argument
    if len(message.command) < 2:
        return await message.reply(
            "⚠️ **Usage:** `/schedule_remove <minutes>`\n\n"
            "**Examples:**\n"
            "• `/schedule_remove 30` — Remove after 30 minutes\n"
            "• `/schedule_remove 60` — Remove after 1 hour\n"
            "• `/schedule_remove 1440` — Remove after 24 hours"
        )

    try:
        minutes = int(message.command[1])
        if minutes <= 0:
            raise ValueError
    except ValueError:
        return await message.reply("❌ Please give a valid positive number of minutes.")

    # Cancel any existing task for this chat
    if chat_id in active_tasks:
        active_tasks[chat_id].cancel()
        active_tasks.pop(chat_id, None)
        del_schedule(chat_id)

    # Save to DB and create task
    run_at = datetime.utcnow() + timedelta(minutes=minutes)
    add_schedule(chat_id, run_at, message.from_user.id)

    loop = asyncio.get_event_loop()
    task = loop.create_task(
        scheduled_remove_task(client, chat_id, minutes * 60, message.from_user.id)
    )
    active_tasks[chat_id] = task

    # Human-friendly time display
    if minutes < 60:
        time_str = f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif minutes < 1440:
        hrs = minutes // 60
        mins = minutes % 60
        time_str = f"{hrs} hour{'s' if hrs != 1 else ''}"
        if mins:
            time_str += f" {mins} min"
    else:
        days = minutes // 1440
        time_str = f"{days} day{'s' if days != 1 else ''}"

    await message.reply(
        f"⏰ **Auto Remove Scheduled!**\n\n"
        f"🕐 Will execute in: **{time_str}**\n"
        f"📅 At (UTC): `{run_at.strftime('%Y-%m-%d %H:%M:%S')}`\n"
        f"🛡️ Admins will be safe.\n\n"
        f"Use `/cancel_remove` to cancel anytime."
    )

# =========================
# ❌ CANCEL SCHEDULE COMMAND
# =========================
@app.on_message(filters.command("cancel_remove") & (filters.group | filters.channel))
async def cancel_remove_cmd(client, message):
    chat_id = message.chat.id

    # Admin check
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        member = await client.get_chat_member(chat_id, message.from_user.id)
        if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            return await message.reply("❌ **Access Denied!** You are not an Admin.")

    if chat_id not in active_tasks and not get_schedule(chat_id):
        return await message.reply("ℹ️ No scheduled remove found for this chat.")

    # Cancel task
    if chat_id in active_tasks:
        active_tasks[chat_id].cancel()
        active_tasks.pop(chat_id, None)
    del_schedule(chat_id)

    await message.reply("✅ **Scheduled remove cancelled successfully!**")

# =========================
# 🔍 CHECK SCHEDULE COMMAND
# =========================
@app.on_message(filters.command("check_schedule") & (filters.group | filters.channel))
async def check_schedule_cmd(client, message):
    chat_id = message.chat.id
    row = get_schedule(chat_id)

    if not row:
        return await message.reply("ℹ️ No scheduled remove is set for this chat.")

    run_at = datetime.fromisoformat(row[0])
    now = datetime.utcnow()
    remaining = run_at - now

    if remaining.total_seconds() <= 0:
        return await message.reply("⏳ Scheduled remove is executing now or just completed.")

    total_secs = int(remaining.total_seconds())
    hrs, rem = divmod(total_secs, 3600)
    mins, secs = divmod(rem, 60)

    time_left = ""
    if hrs:
        time_left += f"{hrs}h "
    if mins:
        time_left += f"{mins}m "
    time_left += f"{secs}s"

    await message.reply(
        f"⏰ **Scheduled Remove Status**\n\n"
        f"📅 Runs at (UTC): `{run_at.strftime('%Y-%m-%d %H:%M:%S')}`\n"
        f"⏳ Time remaining: **{time_left.strip()}**\n\n"
        f"Use `/cancel_remove` to cancel."
    )

# =========================
# 🚫 REMOVE ALL (Instant)
# =========================
@app.on_message(filters.command(["remove_all", "banall"]) & (filters.group | filters.channel))
async def remove_all_handler(client, message):
    chat_id = message.chat.id

    if not is_chat_allowed(chat_id):
        return await message.reply(
            f"❌ **Unauthorized!**\nChat ID `{chat_id}` is not in the whitelist.\nAsk Owner to `/add` this chat."
        )

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        member = await client.get_chat_member(chat_id, message.from_user.id)
        if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            return await message.reply("❌ **Access Denied!** You are not an Admin.")

    try:
        bot = await client.get_chat_member(chat_id, "me")
        if not bot.privileges.can_restrict_members:
            return await message.reply("🚨 I need 'Ban Users' permission!")
    except Exception:
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
    parts = callback.data.split("_")
    action = parts[1]
    auth_user = int(parts[2])

    if auth_user != 0 and callback.from_user.id != auth_user:
        return await callback.answer("Not for you!", show_alert=True)

    if action == "no":
        return await callback.message.edit("❌ Cancelled.")

    msg = await callback.message.edit("🚀 **Processing...**\n🛡️ Admins are safe.")
    count = await do_remove_all(client, callback.message.chat.id, notify_msg=msg)
    await msg.edit(f"✅ **Clean Complete!**\n🗑 Total Removed: {count}")

# =========================
# 🗑️ AUTO-DELETE COMMANDS
# =========================

async def _admin_check(client, message) -> bool:
    """Returns True if user is admin/owner, else sends error and returns False."""
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        member = await client.get_chat_member(message.chat.id, message.from_user.id)
        if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            await message.reply("❌ **Access Denied!** Admins only.")
            return False
    return True

@app.on_message(filters.command("settime") & (filters.group | filters.channel))
async def settime_cmd(client, message):
    if not await _admin_check(client, message):
        return

    # Usage: /settime <value> [s/m/h]
    if len(message.command) < 2:
        return await message.reply(
            "⚠️ **Usage:** `/settime <value> [s/m/h]`\n\n"
            "**Examples:**\n"
            "• `/settime 10 s` → 10 seconds\n"
            "• `/settime 5 m` → 5 minutes\n"
            "• `/settime 1 h` → 1 hour (max 24h)"
        )

    try:
        value = int(message.command[1])
        unit = message.command[2].lower() if len(message.command) >= 3 else "s"
    except (ValueError, IndexError):
        return await message.reply("❌ Invalid format. Use `/settime 10 s` or `/settime 5 m`.")

    if unit == "s":
        delay = value
        unit_label = f"{value} second{'s' if value != 1 else ''}"
    elif unit == "m":
        delay = value * 60
        unit_label = f"{value} minute{'s' if value != 1 else ''}"
    elif unit == "h":
        delay = value * 3600
        unit_label = f"{value} hour{'s' if value != 1 else ''}"
    else:
        return await message.reply("❌ Invalid unit. Use `s` (seconds), `m` (minutes), or `h` (hours).")

    # Max 24 hours
    if delay > 86400:
        return await message.reply("❌ Maximum allowed delay is **24 hours**.")
    if delay <= 0:
        return await message.reply("❌ Delay must be greater than 0.")

    # Get current enabled state (keep it), default enabled=True when setting time
    row = get_autodelete(message.chat.id)
    enabled = row[1] if row else True
    set_autodelete(message.chat.id, delay, enabled)

    await message.reply(
        f"✅ **Auto-Delete delay set to {unit_label}**\n"
        f"{'🟢 Auto-delete is currently **enabled**.' if enabled else '🔴 Auto-delete is **disabled**. Use /enable to turn on.'}"
    )

@app.on_message(filters.command(["gettime", "delayinfo"]) & (filters.group | filters.channel))
async def gettime_cmd(client, message):
    row = get_autodelete(message.chat.id)
    if not row:
        return await message.reply("ℹ️ No auto-delete settings found.\nUse `/settime <value> [s/m/h]` to set one.")

    delay, enabled = row
    if delay < 60:
        time_str = f"{delay} second{'s' if delay != 1 else ''}"
    elif delay < 3600:
        m = delay // 60
        time_str = f"{m} minute{'s' if m != 1 else ''}"
    else:
        h = delay // 3600
        time_str = f"{h} hour{'s' if h != 1 else ''}"

    status = "🟢 **Enabled**" if enabled else "🔴 **Disabled**"
    await message.reply(
        f"⏱️ **Auto-Delete Settings**\n\n"
        f"🕐 Delay: **{time_str}**\n"
        f"Status: {status}"
    )

@app.on_message(filters.command("enable") & (filters.group | filters.channel))
async def enable_autodelete_cmd(client, message):
    if not await _admin_check(client, message):
        return
    toggle_autodelete(message.chat.id, True)
    row = get_autodelete(message.chat.id)
    delay = row[0] if row else 60
    if delay < 60:
        time_str = f"{delay}s"
    elif delay < 3600:
        time_str = f"{delay // 60}m"
    else:
        time_str = f"{delay // 3600}h"
    await message.reply(f"🟢 **Auto-Delete Enabled!**\nMessages will be deleted after **{time_str}**.")

@app.on_message(filters.command("disable") & (filters.group | filters.channel))
async def disable_autodelete_cmd(client, message):
    if not await _admin_check(client, message):
        return
    toggle_autodelete(message.chat.id, False)
    await message.reply("🔴 **Auto-Delete Disabled!**\nMessages will no longer be auto-deleted.")

@app.on_message(filters.command("id"))
async def show_id_cmd(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else "N/A"
    await message.reply(
        f"🆔 **Chat ID:** `{chat_id}`\n"
        f"👤 **Your User ID:** `{user_id}`"
    )

# =========================
# 🗑️ AUTO-DELETE MESSAGE LISTENER
# =========================
@app.on_message(filters.group | filters.channel, group=10)
async def auto_delete_listener(client, message):
    """Listens to all group/channel messages and auto-deletes after set delay."""
    chat_id = message.chat.id
    row = get_autodelete(chat_id)
    if not row:
        return
    delay, enabled = row
    if not enabled:
        return

    async def delete_after(msg, secs):
        await asyncio.sleep(secs)
        try:
            await msg.delete()
        except Exception:
            pass  # Already deleted or no permission

    asyncio.get_event_loop().create_task(delete_after(message, delay))

# =========================
# 🚀 RUN BOT
# =========================
async def main():
    await app.start()
    print("✅ Bot Started! Pending schedules restored.")
    loop = asyncio.get_event_loop()
    restore_schedules(app, loop)
    await asyncio.Event().wait()  # Keep running forever

if __name__ == "__main__":
    print("Bot Starting...")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
