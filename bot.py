import os
import discord
from discord.ext import commands

# GUILD_ID = ID server bạn đã copy từ Discord (chuột phải server → Copy ID)
GUILD_ID = 1264497921617952790   # thay bằng server ID của bạn

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # nếu muốn hỗ trợ prefix

class MyBot(commands.Bot):
    async def setup_hook(self):
        # Load tất cả cogs
        for fn in os.listdir("./cogs"):
            if fn.endswith(".py"):
                await self.load_extension(f"cogs.{fn[:-3]}")

        # Sync slash command vào guild
        try:
            guild = discord.Object(id=GUILD_ID)
            # Copy toàn bộ global commands sang guild
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"🔁 Slash synced {len(synced)} commands cho guild {GUILD_ID}")
        except Exception as e:
            print("❌ Sync error:", e)

bot = MyBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (Bot ID: {bot.user.id})")

# Lấy token từ biến môi trường
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN is not set. Hãy set biến môi trường trước khi chạy.")

bot.run(token)
