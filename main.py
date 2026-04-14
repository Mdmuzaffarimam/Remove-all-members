# Description: Final Bot - MongoDB + delall/delfrom + Auto-Delete + Schedule Remove
# By: MrTamilKiD

import asyncio
import os
import threading
from datetime import datetime, timedelta
from os import environ

from pymongo import MongoClient
from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup, CallbackQuery
from pyrogram.errors import FloodWait

# =========================
# 🖼️ CONFIGURATION
# =========================
START_IMG_URL = "https://files.catbox.moe/5wxw6n.jpg"

API_ID       = int(environ.get("API_ID", 0))
API_HASH     = environ.get("API_HASH", "")
BOT_TOKEN    = environ.get("BOT_TOKEN", "")
OWNER_ID     = int(environ.get("OWNER_ID", "6139759254"))
UNBAN_USERS  = environ.get("UNBAN_USERS", "True") == "True"
MONGODB_URL  = environ.get("MONGODB_URL", "")   # e.g. mongodb+srv://user:pass@cluster.mongodb.net/

# =========================
# 🗄️ MONGODB SETUP
# =========================
_mongo_client = None

def get_db():
    global _mongo_client
    if _mongo_client is None:
        if not MONGODB_URL:
            raise RuntimeError("MONGODB_URL environment variable not set!")
        _mongo_client = MongoClient(MONGODB_URL)
    return _mongo_client["cleanerbot"]   # database name

# Collections
def col_chats():
    return get_db()["chats"]

def col_schedules():
    return get_db()["scheduled_tasks"]

def col_autodelete():
    return get_db()["autodelete_settings"]

# ── Whitelist ──────────────────────────────────────────────
def add_chat_db(chat_id):
    if col_chats().find_one({"chat_id": chat_id}):
        return False
    col_chats().insert_one({"chat_id": chat_id})
    return True

def del_chat_db(chat_id):
    result = col_chats().delete_one({"chat_id": chat_id})
    return result.deleted_count > 0

def get_allowed_chats():
    return [doc["chat_id"] for doc in col_chats().find()]

def is_chat_allowed(chat_id):
    return bool(col_chats().find_one({"chat_id": chat_id}))

# ── Scheduled tasks ────────────────────────────────────────
def add_schedule(chat_id, run_at: datetime, requested_by: int):
    col_schedules().update_one(
        {"chat_id": chat_id},
        {"$set": {"run_at": run_at.isoformat(), "requested_by": requested_by}},
        upsert=True
    )

def del_schedule(chat_id):
    result = col_schedules().delete_one({"chat_id": chat_id})
    return result.deleted_count > 0

def get_all_schedules():
    docs = col_schedules().find()
    return [(d["chat_id"], d["run_at"], d["requested_by"]) for d in docs]

def get_schedule(chat_id):
    doc = col_schedules().find_one({"chat_id": chat_id})
    if not doc:
        return None
    return (doc["run_at"], doc["requested_by"])

# ── Auto-delete settings ───────────────────────────────────
def set_autodelete(chat_id, delay_seconds, enabled=True):
    col_autodelete().update_one(
        {"chat_id": chat_id},
        {"$set": {"delay_seconds": delay_seconds, "enabled": enabled}},
        upsert=True
    )

def toggle_autodelete(chat_id, enabled: bool):
    col_autodelete().update_one(
        {"chat_id": chat_id},
        {"$set": {"enabled": enabled}, "$setOnInsert": {"delay_seconds": 60}},
        upsert=True
    )

def get_autodelete(chat_id):
    doc = col_autodelete().find_one({"chat_id": chat_id})
    if not doc:
        return None
    return (doc["delay_seconds"], doc["enabled"])

# =========================
# ⏱️ IN-MEMORY TASK TRACKER
# =========================
active_tasks: dict[int, asyncio.Task] = {}

# =========================
# 🌐 FLASK KEEP-ALIVE
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
# 🤖 BOT CLIENT
# =========================
app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# =========================
# 🔥 CORE REMOVE ALL MEMBERS
# =========================
async def do_remove_all(client: Client, chat_id: int, notify_msg=None):
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
                await notify_msg.edit(f"✅ Removed {count}. Unbanning...")
            except Exception:
                pass
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            try:
                await client.unban_chat_member(chat_id, member.user.id)
            except Exception:
                pass
    return count

# =========================
# ⏰ SCHEDULED REMOVE RUNNER
# =========================
async def scheduled_remove_task(client: Client, chat_id: int, delay_seconds: float, requested_by: int):
    await asyncio.sleep(delay_seconds)
    del_schedule(chat_id)
    active_tasks.pop(chat_id, None)
    if not is_chat_allowed(chat_id):
        return
    try:
        msg   = await client.send_message(chat_id, "⏰ **Scheduled Remove Started!**\n🛡️ Admins safe hain.")
        count = await do_remove_all(client, chat_id, notify_msg=msg)
        await msg.edit(f"✅ **Scheduled Clean Complete!**\n🗑 Total Removed: **{count}**")
    except Exception as e:
        try:
            await client.send_message(chat_id, f"❌ Scheduled remove failed: {e}")
        except Exception:
            pass

def restore_schedules(client: Client, loop: asyncio.AbstractEventLoop):
    now = datetime.utcnow()
    for chat_id, run_at_str, requested_by in get_all_schedules():
        run_at = datetime.fromisoformat(run_at_str)
        delay  = max((run_at - now).total_seconds(), 0)
        task   = loop.create_task(scheduled_remove_task(client, chat_id, delay, requested_by))
        active_tasks[chat_id] = task

# =========================
# 📌 START COMMAND
# =========================
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_photo(
        photo=START_IMG_URL,
        caption=(
            "👋 **Hi! I'm the Ultimate Channel Cleaner Bot.**\n\n"
            "**👑 Owner Commands (PM):**\n"
            "🔹 `/add <chat_id>` — Whitelist mein add karo\n"
            "🔹 `/remove <chat_id>` — Whitelist se hatao\n"
            "🔹 `/list` — Allowed chats dekho\n\n"
            "**📢 Channel Commands:**\n"
            "🔹 `/remove_all` — Sabhi members remove karo\n"
            "🔹 `/schedule_remove <minutes>` — X mins baad auto remove\n"
            "🔹 `/cancel_remove` — Scheduled remove cancel karo\n"
            "🔹 `/check_schedule` — Timer status dekho\n\n"
            "**🗑️ Message Delete Commands:**\n"
            "🔹 `/delall` — Channel ke SAARE messages delete karo\n"
            "🔹 `/delfrom` — Reply karke bhejo, us se aage sab delete\n\n"
            "**⏱️ Auto-Delete:**\n"
            "🔹 `/settime 10 s` → 10 sec baad delete\n"
            "🔹 `/settime 5 m` → 5 min baad delete\n"
            "🔹 `/settime 1 h` → 1 hour baad delete\n"
            "🔹 `/enable` — Auto-delete on\n"
            "🔹 `/disable` — Auto-delete off\n"
            "🔹 `/gettime` — Current delay dekho\n"
            "🔹 `/id` — Chat ID dekho"
        ),
        reply_markup=Markup([
            [Button("👨‍💻 Developer", url="https://t.me/mimam_officialx"),
             Button("📢 Updates",   url="https://t.me/Mrn_Officialx")]
        ])
    )

# =========================
# 🎮 OWNER COMMANDS
# =========================
@app.on_message(filters.command("add") & filters.user(OWNER_ID))
async def add_chat_cmd(client, message):
    target_id = message.chat.id
    if len(message.command) > 1:
        try:
            target_id = int(message.command[1])
        except Exception:
            return await message.reply("❌ Invalid ID.")
    if add_chat_db(target_id):
        await message.reply(f"✅ **Authorized!**\nChat ID `{target_id}` added.")
    else:
        await message.reply(f"⚠️ Chat `{target_id}` already authorized.")

@app.on_message(filters.command("remove") & filters.user(OWNER_ID))
async def del_chat_cmd(client, message):
    target_id = message.chat.id
    if len(message.command) > 1:
        try:
            target_id = int(message.command[1])
        except Exception:
            return await message.reply("❌ Invalid ID.")
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
# 🗑️ DELETE ALL MESSAGES — /delall
# =========================
@app.on_message(filters.command("delall") & (filters.group | filters.channel))
async def delall_cmd(client, message):
    chat_id = message.chat.id

    if not is_chat_allowed(chat_id):
        return await message.reply(f"❌ **Unauthorized!**\nChat ID `{chat_id}` whitelist mein nahi hai.")

    user_id = message.from_user.id if message.from_user else 0
    await message.reply(
        "⚠️ **CONFIRMATION** ⚠️\n\n"
        "Channel ke **SAARE messages** delete karne hain?\n"
        "Yeh action **UNDO nahi ho sakta!**",
        reply_markup=Markup([
            [Button("✅ Haan, Delete Karo", callback_data=f"delall_yes_{user_id}"),
             Button("❌ Cancel",            callback_data=f"delall_no_{user_id}")]
        ])
    )

@app.on_callback_query(filters.regex(r"^delall_(yes|no)_"))
async def delall_callback(client, callback: CallbackQuery):
    parts     = callback.data.split("_")
    action    = parts[1]
    auth_user = int(parts[2])

    if auth_user != 0 and callback.from_user.id != auth_user:
        return await callback.answer("Yeh tumhare liye nahi hai!", show_alert=True)

    if action == "no":
        return await callback.message.edit("❌ Cancelled.")

    chat_id     = callback.message.chat.id
    msg         = await callback.message.edit("🗑️ **Deleting all messages...**")
    count       = 0
    current_id  = callback.message.id
    batch       = []

    for msg_id in range(1, current_id + 1):
        batch.append(msg_id)
        if len(batch) == 100:
            try:
                deleted = await client.delete_messages(chat_id, batch)
                count += deleted
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                pass
            batch = []
            if count % 500 == 0 and count > 0:
                try:
                    await msg.edit(f"🗑️ Deleted {count} messages...")
                except Exception:
                    pass

    if batch:
        try:
            deleted = await client.delete_messages(chat_id, batch)
            count += deleted
        except Exception:
            pass

    try:
        await msg.edit(f"✅ **Delete Complete!**\n🗑 Messages Deleted: **{count}**")
    except Exception:
        pass

# =========================
# 🗑️ DELETE FROM MESSAGE — /delfrom
# =========================
@app.on_message(filters.command("delfrom") & (filters.group | filters.channel))
async def delfrom_cmd(client, message):
    chat_id = message.chat.id

    if not is_chat_allowed(chat_id):
        return await message.reply(f"❌ **Unauthorized!**\nChat ID `{chat_id}` whitelist mein nahi hai.")

    if not message.reply_to_message:
        return await message.reply(
            "ℹ️ **Usage:** Kisi message ko reply karke `/delfrom` bhejo.\n"
            "Us message se lekar aage ke sab delete ho jayenge."
        )

    from_msg_id = message.reply_to_message.id
    current_id  = message.id
    user_id     = message.from_user.id if message.from_user else 0

    await message.reply(
        f"⚠️ **CONFIRMATION** ⚠️\n\n"
        f"Message ID `{from_msg_id}` se lekar aage ke **saare messages** delete karne hain?",
        reply_markup=Markup([
            [Button("✅ Haan, Delete Karo", callback_data=f"delfrom_yes_{user_id}_{from_msg_id}_{current_id}"),
             Button("❌ Cancel",            callback_data=f"delfrom_no_{user_id}")]
        ])
    )

@app.on_callback_query(filters.regex(r"^delfrom_(yes|no)_"))
async def delfrom_callback(client, callback: CallbackQuery):
    parts  = callback.data.split("_")
    action = parts[1]

    if action == "no":
        auth_user = int(parts[2])
        if auth_user != 0 and callback.from_user.id != auth_user:
            return await callback.answer("Yeh tumhare liye nahi hai!", show_alert=True)
        return await callback.message.edit("❌ Cancelled.")

    auth_user   = int(parts[2])
    from_msg_id = int(parts[3])
    current_id  = int(parts[4])

    if auth_user != 0 and callback.from_user.id != auth_user:
        return await callback.answer("Yeh tumhare liye nahi hai!", show_alert=True)

    chat_id = callback.message.chat.id
    msg     = await callback.message.edit(f"🗑️ **Deleting from message {from_msg_id}...**")
    count   = 0
    batch   = []

    for msg_id in range(from_msg_id, current_id + 1):
        batch.append(msg_id)
        if len(batch) == 100:
            try:
                deleted = await client.delete_messages(chat_id, batch)
                count += deleted
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                pass
            batch = []
            if count % 300 == 0 and count > 0:
                try:
                    await msg.edit(f"🗑️ Deleted {count} messages...")
                except Exception:
                    pass

    if batch:
        try:
            deleted = await client.delete_messages(chat_id, batch)
            count += deleted
        except Exception:
            pass

    try:
        await msg.edit(
            f"✅ **Delete Complete!**\n"
            f"🗑 Messages Deleted: **{count}**\n"
            f"📍 From Message ID: `{from_msg_id}`"
        )
    except Exception:
        pass

# =========================
# 🗑️ AUTO-DELETE COMMANDS
# =========================
@app.on_message(filters.command("settime") & (filters.group | filters.channel))
async def settime_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply(
            "⚠️ **Usage:** `/settime <value> [s/m/h]`\n\n"
            "• `/settime 10 s` → 10 seconds\n"
            "• `/settime 5 m` → 5 minutes\n"
            "• `/settime 1 h` → 1 hour (max 24h)"
        )
    try:
        value = int(message.command[1])
        unit  = message.command[2].lower() if len(message.command) >= 3 else "s"
    except (ValueError, IndexError):
        return await message.reply("❌ Invalid format. Example: `/settime 10 s`")

    if unit == "s":
        delay, label = value, f"{value} second{'s' if value!=1 else ''}"
    elif unit == "m":
        delay, label = value * 60, f"{value} minute{'s' if value!=1 else ''}"
    elif unit == "h":
        delay, label = value * 3600, f"{value} hour{'s' if value!=1 else ''}"
    else:
        return await message.reply("❌ Unit must be `s`, `m`, or `h`.")

    if delay > 86400:
        return await message.reply("❌ Maximum delay is **24 hours**.")
    if delay <= 0:
        return await message.reply("❌ Delay must be > 0.")

    row     = get_autodelete(message.chat.id)
    enabled = row[1] if row else True
    set_autodelete(message.chat.id, delay, enabled)
    await message.reply(
        f"✅ **Auto-Delete delay set to {label}**\n"
        f"{'🟢 Auto-delete is **enabled**.' if enabled else '🔴 Auto-delete is **disabled**. Use /enable.'}"
    )

@app.on_message(filters.command(["gettime", "delayinfo"]) & (filters.group | filters.channel))
async def gettime_cmd(client, message):
    row = get_autodelete(message.chat.id)
    if not row:
        return await message.reply("ℹ️ No auto-delete settings.\nUse `/settime <value> [s/m/h]`.")
    delay, enabled = row
    ts = f"{delay}s" if delay < 60 else (f"{delay//60}m" if delay < 3600 else f"{delay//3600}h")
    await message.reply(
        f"⏱️ **Auto-Delete Settings**\n\n"
        f"🕐 Delay: **{ts}**\n"
        f"Status: {'🟢 **Enabled**' if enabled else '🔴 **Disabled**'}"
    )

@app.on_message(filters.command("enable") & (filters.group | filters.channel))
async def enable_cmd(client, message):
    toggle_autodelete(message.chat.id, True)
    row = get_autodelete(message.chat.id)
    d   = row[0] if row else 60
    ts  = f"{d}s" if d < 60 else (f"{d//60}m" if d < 3600 else f"{d//3600}h")
    await message.reply(f"🟢 **Auto-Delete Enabled!**\nMessages delete after **{ts}**.")

@app.on_message(filters.command("disable") & (filters.group | filters.channel))
async def disable_cmd(client, message):
    toggle_autodelete(message.chat.id, False)
    await message.reply("🔴 **Auto-Delete Disabled!**")

@app.on_message(filters.command("id"))
async def show_id_cmd(client, message):
    uid = message.from_user.id if message.from_user else "N/A"
    await message.reply(f"🆔 **Chat ID:** `{message.chat.id}`\n👤 **Your User ID:** `{uid}`")

# =========================
# ⏰ SCHEDULE REMOVE
# =========================
@app.on_message(filters.command("schedule_remove") & (filters.group | filters.channel))
async def schedule_remove_cmd(client, message):
    chat_id = message.chat.id
    if not is_chat_allowed(chat_id):
        return await message.reply(f"❌ **Unauthorized!**\nChat ID `{chat_id}` whitelist mein nahi hai.")

    if len(message.command) < 2:
        return await message.reply(
            "⚠️ **Usage:** `/schedule_remove <minutes>`\n\n"
            "• `/schedule_remove 30` → 30 minutes baad\n"
            "• `/schedule_remove 60` → 1 hour baad\n"
            "• `/schedule_remove 1440` → 24 hours baad"
        )
    try:
        minutes = int(message.command[1])
        if minutes <= 0:
            raise ValueError
    except ValueError:
        return await message.reply("❌ Valid number do. Example: `/schedule_remove 30`")

    if chat_id in active_tasks:
        active_tasks[chat_id].cancel()
        active_tasks.pop(chat_id, None)
        del_schedule(chat_id)

    run_at = datetime.utcnow() + timedelta(minutes=minutes)
    req_by = message.from_user.id if message.from_user else OWNER_ID
    add_schedule(chat_id, run_at, req_by)

    loop = asyncio.get_event_loop()
    task = loop.create_task(scheduled_remove_task(client, chat_id, minutes * 60, req_by))
    active_tasks[chat_id] = task

    if minutes < 60:
        ts = f"{minutes} minute{'s' if minutes!=1 else ''}"
    elif minutes < 1440:
        h, m = divmod(minutes, 60)
        ts = f"{h}h" + (f" {m}m" if m else "")
    else:
        ts = f"{minutes//1440} day{'s' if minutes//1440!=1 else ''}"

    await message.reply(
        f"⏰ **Auto Remove Scheduled!**\n\n"
        f"🕐 Execute in: **{ts}**\n"
        f"📅 At (UTC): `{run_at.strftime('%Y-%m-%d %H:%M:%S')}`\n"
        f"🛡️ Admins safe rahenge.\n\nCancel: `/cancel_remove`"
    )

@app.on_message(filters.command("cancel_remove") & (filters.group | filters.channel))
async def cancel_remove_cmd(client, message):
    chat_id = message.chat.id
    if chat_id not in active_tasks and not get_schedule(chat_id):
        return await message.reply("ℹ️ Koi scheduled remove nahi mila.")
    if chat_id in active_tasks:
        active_tasks[chat_id].cancel()
        active_tasks.pop(chat_id, None)
    del_schedule(chat_id)
    await message.reply("✅ **Scheduled remove cancel ho gaya!**")

@app.on_message(filters.command("check_schedule") & (filters.group | filters.channel))
async def check_schedule_cmd(client, message):
    row = get_schedule(message.chat.id)
    if not row:
        return await message.reply("ℹ️ Koi scheduled remove set nahi hai.")
    run_at    = datetime.fromisoformat(row[0])
    remaining = run_at - datetime.utcnow()
    if remaining.total_seconds() <= 0:
        return await message.reply("⏳ Scheduled remove execute ho raha hai ya complete ho gaya.")
    total = int(remaining.total_seconds())
    h, r  = divmod(total, 3600)
    m, s  = divmod(r, 60)
    tl    = (f"{h}h " if h else "") + (f"{m}m " if m else "") + f"{s}s"
    await message.reply(
        f"⏰ **Scheduled Remove Status**\n\n"
        f"📅 Runs at (UTC): `{run_at.strftime('%Y-%m-%d %H:%M:%S')}`\n"
        f"⏳ Time remaining: **{tl.strip()}**\n\nCancel: `/cancel_remove`"
    )

# =========================
# 🚫 REMOVE ALL MEMBERS
# =========================
@app.on_message(filters.command(["remove_all", "banall"]) & (filters.group | filters.channel))
async def remove_all_handler(client, message):
    chat_id = message.chat.id
    if not is_chat_allowed(chat_id):
        return await message.reply(f"❌ **Unauthorized!**\nChat ID `{chat_id}` whitelist mein nahi hai.")

    try:
        bot = await client.get_chat_member(chat_id, "me")
        if not bot.privileges or not bot.privileges.can_restrict_members:
            return await message.reply("🚨 Mujhe 'Ban Users' permission chahiye!")
    except Exception:
        return await message.reply("🚨 Main admin nahi hoon!")

    user_id = message.from_user.id if message.from_user else 0
    await message.reply(
        "⚠️ **CONFIRMATION** ⚠️\n\nSabhi members remove karne hain? Admins safe rahenge.",
        reply_markup=Markup([
            [Button("✅ Yes, Remove All", callback_data=f"ban_yes_{user_id}"),
             Button("❌ Cancel",          callback_data=f"ban_no_{user_id}")]
        ])
    )

@app.on_callback_query(filters.regex(r"^ban_(yes|no)_"))
async def ban_callback(client, callback: CallbackQuery):
    parts     = callback.data.split("_")
    action    = parts[1]
    auth_user = int(parts[2])
    if auth_user != 0 and callback.from_user.id != auth_user:
        return await callback.answer("Yeh tumhare liye nahi hai!", show_alert=True)
    if action == "no":
        return await callback.message.edit("❌ Cancelled.")
    msg   = await callback.message.edit("🚀 **Processing...**\n🛡️ Admins safe hain.")
    count = await do_remove_all(client, callback.message.chat.id, notify_msg=msg)
    await msg.edit(f"✅ **Clean Complete!**\n🗑 Total Removed: **{count}**")

# =========================
# 🗑️ AUTO-DELETE MESSAGE LISTENER
# =========================
@app.on_message(filters.group | filters.channel, group=10)
async def auto_delete_listener(client, message):
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
            pass

    asyncio.get_event_loop().create_task(delete_after(message, delay))

# =========================
# 🚀 RUN BOT
# =========================
async def main():
    await app.start()
    print("✅ Bot Started!")
    loop = asyncio.get_event_loop()
    restore_schedules(app, loop)
    await asyncio.Event().wait()

if __name__ == "__main__":
    print("Bot Starting...")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
