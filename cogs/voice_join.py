import discord
from discord.ext import commands
from discord import app_commands

class VoiceJoin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # /join-voice channel:#kênh-voice
    @app_commands.command(name="join-voice", description="Cho bot vào voice channel đã chọn và tự tắt mic/loa")
    @app_commands.describe(channel="Voice channel để bot vào")
    async def join_voice(self, itx: discord.Interaction, channel: discord.VoiceChannel):
        await itx.response.defer(ephemeral=True, thinking=True)
        guild = itx.guild
        if guild is None:
            return await itx.followup.send("⚠️ Lệnh chỉ dùng trong server.", ephemeral=True)

        # Kiểm tra quyền cơ bản
        me = guild.me or await guild.fetch_member(self.bot.user.id)
        perms = channel.permissions_for(me)
        if not perms.connect:
            return await itx.followup.send("⛔ Bot thiếu quyền **Connect** ở kênh này.", ephemeral=True)
        # (Speak không bắt buộc nếu chỉ treo, nhưng nên có)
        if not perms.speak:
            await itx.followup.send("ℹ️ Bot thiếu quyền **Speak**, nhưng vẫn sẽ vào và treo (mute/deaf).", ephemeral=True)

        vc = guild.voice_client
        try:
            if vc and vc.is_connected():
                # Đang ở voice: chuyển kênh nếu khác
                if vc.channel.id != channel.id:
                    await vc.move_to(channel)
            else:
                # Chưa ở voice: connect
                await channel.connect(reconnect=True)

            # Tự tắt mic & loa (self_mute/self_deaf)
            # connect()/move_to() không set được trực tiếp => đổi trạng thái sau khi kết nối
            try:
                await guild.change_voice_state(channel=channel, self_mute=True, self_deaf=True)
            except Exception:
                # fallback: một số shard/permission có thể không cho set, bỏ qua
                pass

            await itx.followup.send(f"✅ Đã vào **{channel.name}** và **mute + deaf**. Bot sẽ **không tự disconnect**.", ephemeral=True)

        except discord.Forbidden:
            await itx.followup.send("⛔ Bot bị chặn vào kênh (Forbidden). Kiểm tra lại quyền Connect/Move Members.", ephemeral=True)
        except discord.HTTPException as e:
            await itx.followup.send(f"❌ Lỗi HTTP khi vào kênh: `{e}`", ephemeral=True)
        except Exception as e:
            await itx.followup.send(f"❌ Lỗi không xác định: `{e}`", ephemeral=True)

    # Tiện ích: cho bot rời voice khi bạn muốn
    @app_commands.command(name="leave-voice", description="Cho bot rời voice (tùy chọn, nếu bạn muốn)")
    async def leave_voice(self, itx: discord.Interaction):
        guild = itx.guild
        if guild and guild.voice_client and guild.voice_client.is_connected():
            await guild.voice_client.disconnect(force=True)
            await itx.response.send_message("👋 Bot đã rời voice.", ephemeral=True)
        else:
            await itx.response.send_message("ℹ️ Bot không ở trong voice.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceJoin(bot))
