# Description: A simple Telegram Bot to remove all members from a group.
# By: MrTamilKiD
# Updates: "For more updates join @KR_BotX"
# Created on: 2025-03-07
# Last Updated: 2025-03-07
#
# Dependencies:
#   pyrogram and pyrofork (for Telegram API)
#   python-dotenv (for environment variables)
#   Flask (for webhooks, web server)
#   gunicorn (for deployment)
#   python 3.6 or higher

import asyncio
from os import environ
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from pyrogram.errors import FloodWait, RPCError

# Telegram API Credentials
API_ID = int(environ.get("API_ID", 23631217))  # Replace with your API ID
API_HASH = environ.get("API_HASH", "567c6df308dc6901790309499f729d12")  # Replace with your API Hash
BOT_TOKEN = environ.get("BOT_TOKEN", "")  # Replace with your Bot Token
UNBAN_USERS = environ.get("UNBAN_USERS", "True") == "True"  # Unban users after removing them
BAN_CMD = ["remove_all", "removeall", "banall", "ban_all"]  # Command to trigger the bot

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply(
        "👋 Hi! I'm a Group Management Bot!\n\n"
        "✨ What I can do:\n"
        "🚫 Remove all members from a group\n\n"
        "📝 How to use me:\n"
        "1️⃣ Add me as admin in your group\n"
        "2️⃣ Give me 'Ban Users' permission\n"
        "3️⃣ Use /remove_all command\n\n"
        "⚠️ Important: I need 'Ban Users' permission to work!",
        reply_markup=Markup(
            [
                [
                    Button("👨‍💻 Developer", url="https://t.me/mimam_officialx"),
                    Button("💬 Support", url="https://t.me/MRN_Chat_Group"),
                ],
                [Button("⭐ Source Code", url="https://t.me/mimam_officialx")],
            ]
        ),
        quote=True,
        disable_web_page_preview=True,
    )

@app.on_message(filters.command("help") & filters.private)
async def help(client, message):
    await message.reply(
        "🤖 Simple Bot Guide:\n\n"
        "📍 Commands:\n"
        "/remove_all - Remove everyone from group\n\n"
        "📌 Quick Setup:\n"
        "1️⃣ Make me admin\n"
        "2️⃣ Give 'Ban Users' permission\n"
        "3️⃣ That's it!",
        reply_markup=Markup(
            [
                [
                    Button("👨‍💻 Developer", url="https://t.me/mimam_officialx"),
                    Button("💬 Support", url="https://t.me/MRN_Chat_Group"),
                ],
                [Button("⭐ Source Code", url="https://t.me/mimam_officialx")],
            ]
        ),
        disable_web_page_preview=True,
        quote=True,
    )

@app.on_message(filters.command(BAN_CMD) & (filters.group | filters.channel))
async def remove_all_users(client, message):
    chat_id = message.chat.id
    # Get bot's admin status
    bot_admin = await client.get_chat_member(chat_id, "me")
    # Check if the bot has "Ban Users" permission
    if not bot_admin.privileges or not bot_admin.privileges.can_restrict_members:
        await message.reply("🚨 I need 'Ban Users' permission to remove members!")
        return

    count = 0
    update_message = await message.reply(
        "🔄 Starting to remove members...\n\n⌛ Please wait patiently\n\n🔹 Current progress: 0 members", quote=True
    )

    async for member in client.get_chat_members(chat_id):
        user_id = member.user.id

        # Skip admins & owner
        if member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            continue

        try:
            await client.ban_chat_member(chat_id, user_id)
            count += 1

            # Send an update every 10 users
            if count % 10 == 0:
                await update_message.edit(f"🔄 Progress Update:\n\n✅ Members removed: {count}\n⏳ Please wait...")

        except FloodWait as e:
            await asyncio.sleep(e.value)
        except RPCError as e:
            print(f"Error removing user {user_id}: {e}")

    if UNBAN_USERS:
        ban_users = []
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            ban_users.append(member.user.id)
        for user_id in ban_users:
            try:
                await client.unban_chat_member(chat_id, user_id)
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except RPCError as e:
                print(f"Error unbanning user {user_id}: {e}")

    # Final confirmation message
    await update_message.edit(
        f"🎉 Operation Complete!\n\n"
        f"👥 Total Members Removed: {count}\n"
        f"✨ Group has been cleaned successfully"
    )

@app.on_message(filters.command("unbanall") & (filters.group | filters.channel))
async def unban_all_users(client, message):
    chat_id = message.chat.id
    # Get bot's admin status
    bot_admin = await client.get_chat_member(chat_id, "me")
    # Check if the bot has "Ban Users" permission
    if not bot_admin.privileges or not bot_admin.privileges.can_restrict_members:
        await message.reply("🚨 I need 'Ban Users' permission to unban members!")
        return

    count = 0
    unban_all_users = []
    update_message = await message.reply(
        "🔄 Starting to unban members...\n\n⌛ Please wait patiently\n\n🔹 Current progress: 0 members", quote=True
    )

    try:
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            unban_all_users.append(member.user.id)
            count += 1
            # Send an update every 10 users
            if count % 10 == 0:  # Changed to 10 for consistency with remove_all_users
                await update_message.edit(f"🔄 Progress Update:\n\n✅ Members unbanned: {count}\n⏳ Please wait...")

        for user_id in unban_all_users:
            await client.unban_chat_member(chat_id, user_id)

    except FloodWait as e:
        await asyncio.sleep(e.value)
    except RPCError as e:
        print(f"Error unbanning user {user_id}: {e}")

    # Final confirmation message
    await update_message.edit(
        f"🎉 Operation Complete!\n\n"
        f"👥 Total Members Unbanned: {count}\n"
        f"✨ Group has been cleaned successfully"
    )

if __name__ == "__main__":
    print("Bot is running!")
    app.run()
