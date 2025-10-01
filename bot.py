import os
import discord
from discord.ext import commands
from discord import app_commands

# ====== Cấu hình ======
GUILD_ID = 1264497921617952790   # thay bằng server ID của bạn

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # nếu bạn muốn dùng lệnh prefix (!)

# ====== Cog viết trực tiếp trong file ======
class VoiceJoin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="join-voice", description="Cho bot vào voice channel đã chọn và tự tắt mic/loa")
    @app_commands.describe(channel="Voice channel để bot vào")
    async def join_voice(self, itx: discord.Interaction, channel: discord.VoiceChannel):
        await itx.response.defer(ephemeral=True, thinking=True)
        guild = itx.guild
        if guild is None:
            return await itx.followup.send("⚠️ Lệnh chỉ dùng trong server.", ephemeral=True)

        me = guild.me or await guild.fetch_member(self.bot.user.id)
        perms = channel.permissions_for(me)
        if not perms.connect:
            return await itx.followup.send("⛔ Bot thiếu quyền **Connect** ở kênh này.", ephemeral=True)
        if not perms.speak:
            await itx.followup.send("ℹ️ Bot thiếu quyền **Speak**, vẫn vào và treo (mute/deaf).", ephemeral=True)

        vc = guild.voice_client
        try:
            if vc and vc.is_connected():
                if vc.channel.id != channel.id:
                    await vc.move_to(channel)
            else:
                await channel.connect(reconnect=True)

            try:
                await guild.change_voice_state(channel=channel, self_mute=True, self_deaf=True)
            except Exception:
                pass

            await itx.followup.send(
                f"✅ Đã vào **{channel.name}** và **mute + deaf**. Bot sẽ **không tự disconnect**.",
                ephemeral=True
            )

        except discord.Forbidden:
            await itx.followup.send("⛔ Bot bị chặn vào kênh (Forbidden). Kiểm tra quyền Connect/Move Members.", ephemeral=True)
        except discord.HTTPException as e:
            await itx.followup.send(f"❌ Lỗi HTTP khi vào kênh: `{e}`", ephemeral=True)
        except Exception as e:
            await itx.followup.send(f"❌ Lỗi không xác định: `{e}`", ephemeral=True)

    @app_commands.command(name="leave-voice", description="Cho bot rời voice (nếu đang ở trong kênh)")
    async def leave_voice(self, itx: discord.Interaction):
        guild = itx.guild
        if guild and guild.voice_client and guild.voice_client.is_connected():
            await guild.voice_client.disconnect(force=True)
            await itx.response.send_message("👋 Bot đã rời voice.", ephemeral=True)
        else:
            await itx.response.send_message("ℹ️ Bot không ở trong voice.", ephemeral=True)

# ====== Bot single-file (KHÔNG load thư mục cogs) ======
class MyBot(commands.Bot):
    async def setup_hook(self):
        await self.add_cog(VoiceJoin(self))
        try:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"🔁 Slash synced {len(synced)} commands cho guild {GUILD_ID}")
        except Exception as e:
            print("❌ Sync error:", e)

bot = MyBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (Bot ID: {bot.user.id})")

# ====== Chạy bot ======
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN is not set. Hãy set biến môi trường trước khi chạy.")
bot.run(token)
