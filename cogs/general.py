from discord import app_commands
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Lệnh prefix
    @commands.command()
    async def ping(self, ctx):
        await ctx.send(f"Pong! 🏓 {round(self.bot.latency*1000)}ms")

    # Lệnh slash
    @app_commands.command(name="ping", description="Kiểm tra độ trễ (slash command)")
    async def slash_ping(self, interaction):
        await interaction.response.send_message(
            f"Pong! 🏓 {round(self.bot.latency*1000)}ms"
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
