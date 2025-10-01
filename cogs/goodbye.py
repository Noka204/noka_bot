# cogs/goodbye.py
import os, json, re
from datetime import datetime, timezone
import discord
from discord.ext import commands
from discord import app_commands

CONFIG = "config.json"
HEX = re.compile(r"^#(?:[0-9a-fA-F]{6})$")

DEFAULT_CFG = {
    "goodbye channel": None,   # ID kênh text sẽ gửi lời tạm biệt
    "goodbye embed": None      # object cấu hình embed, hoặc None để dùng text thường
}

# ------------------- config helpers -------------------
def load_cfg() -> dict:
    if not os.path.exists(CONFIG):
        return DEFAULT_CFG.copy()
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        data = {}
    out = DEFAULT_CFG.copy()
    out.update(data)
    return out

def save_cfg(cfg: dict):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ------------------- embed builder -------------------
def build_goodbye_embed(member: discord.Member | discord.User, guild: discord.Guild, cfg: dict):
    fe = cfg.get("goodbye embed")
    if not fe:
        return None

    # color
    col = fe.get("color") or "#ff6b6b"
    try:
        color = discord.Color.from_str(col)
    except Exception:
        color = discord.Color.red()

    # desc vars
    uname = getattr(member, "mention", None) or getattr(member, "name", "Một thành viên")
    desc = (fe.get("description") or "").replace("{user}", uname).replace("{server}", guild.name)

    e = discord.Embed(
        title=fe.get("title") or "",
        description=desc,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )

    # thumbnail
    thumb = fe.get("thumbnail")
    if thumb == "avatar" and isinstance(member, (discord.Member, discord.User)):
        av = getattr(member, "display_avatar", None) or getattr(member, "avatar", None)
        if av:
            e.set_thumbnail(url=av.url)
    elif isinstance(thumb, str) and thumb.startswith("http"):
        e.set_thumbnail(url=thumb)

    # image
    if isinstance(fe.get("image"), str) and fe["image"].startswith("http"):
        e.set_image(url=fe["image"])

    # footer
    if fe.get("footer"):
        e.set_footer(text=fe["footer"].replace("{server}", guild.name))

    return e

# ------------------- UI modals & view -------------------
class TextModal(discord.ui.Modal):
    def __init__(self, field: str, title: str, label: str, placeholder: str = "", max_len: int = 4000):
        super().__init__(title=title, timeout=180)
        self.field = field
        self.input = discord.ui.TextInput(
            label=label,
            style=discord.TextStyle.paragraph,
            placeholder=placeholder,
            required=False,
            max_length=max_len
        )
        self.add_item(self.input)

    async def on_submit(self, itx: discord.Interaction):
        cfg = load_cfg()
        fe = cfg.get("goodbye embed") or {}
        value = (self.input.value or "").strip()
        fe[self.field] = value if value else None
        cfg["goodbye embed"] = fe
        save_cfg(cfg)
        await itx.response.send_message("✅ Đã lưu.", ephemeral=True)

class ColorModal(discord.ui.Modal, title="Màu Embed (#RRGGBB)"):
    color = discord.ui.TextInput(label="Color", placeholder="#ff6b6b", required=True, max_length=7)

    async def on_submit(self, itx: discord.Interaction):
        val = str(self.color.value).strip()
        if not HEX.match(val):
            return await itx.response.send_message("⚠️ Sai định dạng. Dùng **#RRGGBB**.", ephemeral=True)
        cfg = load_cfg()
        fe = cfg.get("goodbye embed") or {}
        fe["color"] = val
        cfg["goodbye embed"] = fe
        save_cfg(cfg)
        await itx.response.send_message("✅ Đã lưu màu.", ephemeral=True)

class GoodbyeSetupView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.author_id and not itx.user.guild_permissions.manage_guild:
            await itx.response.send_message("⛔ Chỉ người mở menu hoặc quản trị mới thao tác.", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Chọn kênh gửi goodbye",
        channel_types=[discord.ChannelType.text]
    )
    async def sel_channel(self, itx: discord.Interaction, sel: discord.ui.ChannelSelect):
        ch: discord.TextChannel = sel.values[0]
        cfg = load_cfg()
        cfg["goodbye channel"] = ch.id
        save_cfg(cfg)
        await itx.response.send_message(f"✅ Goodbye channel: {ch.mention}", ephemeral=True)

    @discord.ui.button(label="Tiêu đề", style=discord.ButtonStyle.primary)
    async def btn_title(self, itx: discord.Interaction, _):
        await itx.response.send_modal(TextModal("title", "Tiêu đề Embed", "Nhập tiêu đề"))

    @discord.ui.button(label="Mô tả", style=discord.ButtonStyle.primary)
    async def btn_desc(self, itx: discord.Interaction, _):
        ph = "Ví dụ: {user} đã rời {server}. Hẹn gặp lại!"
        await itx.response.send_modal(TextModal("description", "Mô tả Embed", "Nội dung", ph))

    @discord.ui.button(label="Màu (#RRGGBB)", style=discord.ButtonStyle.secondary)
    async def btn_color(self, itx: discord.Interaction, _):
        await itx.response.send_modal(ColorModal())

    @discord.ui.button(label="Ảnh lớn (image URL)", style=discord.ButtonStyle.secondary)
    async def btn_image(self, itx: discord.Interaction, _):
        await itx.response.send_modal(TextModal("image", "Ảnh lớn", "URL (http…)", "https://…"))

    @discord.ui.button(label="Thumbnail (avatar/URL)", style=discord.ButtonStyle.secondary)
    async def btn_thumb(self, itx: discord.Interaction, _):
        await itx.response.send_modal(TextModal("thumbnail", "Thumbnail", "avatar hoặc URL", "avatar"))

    @discord.ui.button(label="Footer", style=discord.ButtonStyle.secondary)
    async def btn_footer(self, itx: discord.Interaction, _):
        await itx.response.send_modal(TextModal("footer", "Footer", "Nhập footer", "{server} luôn nhớ bạn"))

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.success)
    async def btn_preview(self, itx: discord.Interaction, _):
        cfg = load_cfg()
        e = build_goodbye_embed(itx.user, itx.guild, cfg)
        if not e:
            return await itx.response.send_message("⚠️ Chưa có cấu hình embed. Hãy thiết lập trước.", ephemeral=True)
        await itx.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Reset embed", style=discord.ButtonStyle.danger)
    async def btn_reset(self, itx: discord.Interaction, _):
        cfg = load_cfg()
        cfg["goodbye embed"] = None  # key chính xác
        save_cfg(cfg)
        await itx.response.send_message("🗑️ Đã xoá cấu hình embed goodbye.", ephemeral=True)

# ------------------- Cog -------------------
class GoodbyeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    goodbye = app_commands.Group(name="goodbye", description="Cấu hình lời tạm biệt")

    @goodbye.command(name="setup", description="Mở menu setup Embed + kênh tạm biệt")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_setup(self, itx: discord.Interaction):
        await itx.response.send_message("⚙️ Setup goodbye", view=GoodbyeSetupView(itx.user.id), ephemeral=True)

    @goodbye.command(name="set-channel", description="Chọn kênh gửi lời tạm biệt (mặc định)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_set_channel(self, itx: discord.Interaction, channel: discord.TextChannel):
        cfg = load_cfg()
        cfg["goodbye channel"] = channel.id
        save_cfg(cfg)
        await itx.response.send_message(f"✅ Đã set kênh goodbye: {channel.mention}", ephemeral=True)

    # ------- Preset / Disable embed -------
    @goodbye.command(name="preset", description="Tạo embed goodbye mẫu (khởi tạo nhanh)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_preset(self, itx: discord.Interaction):
        cfg = load_cfg()
        cfg["goodbye embed"] = {
            "title": "Tạm biệt!",
            "description": "{user} đã rời {server}. Hẹn gặp lại nhé!",
            "color": "#ff6b6b",
            "thumbnail": "avatar",
            "image": None,
            "footer": "{server} luôn nhớ bạn"
        }
        save_cfg(cfg)
        await itx.response.send_message("✅ Đã tạo embed goodbye mặc định.", ephemeral=True)

    @goodbye.command(name="disable-embed", description="Tắt embed goodbye (quay lại dạng text thường)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_disable_embed(self, itx: discord.Interaction):
        cfg = load_cfg()
        cfg["goodbye embed"] = None
        save_cfg(cfg)
        await itx.response.send_message("🛑 Đã tắt embed goodbye (sẽ gửi text).", ephemeral=True)

    # ------- Test gửi thử -------
    @goodbye.command(name="test", description="Gửi thử goodbye (không cần ai rời server)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_test(
        self,
        itx: discord.Interaction,
        channel: discord.TextChannel | None = None,
        user: discord.Member | None = None
    ):
        cfg = load_cfg()
        # kênh đích
        dest = channel
        if dest is None:
            ch_id = cfg.get("goodbye channel")
            dest = itx.guild.get_channel(ch_id) if ch_id else None
        if not isinstance(dest, discord.TextChannel):
            return await itx.response.send_message("⚠️ Chưa chọn kênh và cũng chưa cấu hình `goodbye channel`.", ephemeral=True)

        target = user or itx.user  # ai sẽ hiện trên embed
        e = build_goodbye_embed(target, itx.guild, cfg)
        try:
            if e:
                await dest.send(embed=e)
            else:
                await dest.send(f"👋 {target.name} đã rời **{itx.guild.name}**. (test)")
            await itx.response.send_message(f"✅ Đã gửi thử vào {dest.mention}", ephemeral=True)
        except discord.Forbidden:
            await itx.response.send_message("⛔ Bot không có quyền gửi ở kênh này.", ephemeral=True)
        except Exception as ex:
            await itx.response.send_message(f"❌ Lỗi: {ex}", ephemeral=True)

    # ------- Listener thật -------
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        cfg = load_cfg()
        ch_id = cfg.get("goodbye channel")
        if not ch_id:
            return
        guild = member.guild
        channel = guild.get_channel(ch_id)
        if not isinstance(channel, discord.TextChannel):
            return

        e = build_goodbye_embed(member, guild, cfg)
        try:
            if e:
                await channel.send(embed=e)
            else:
                await channel.send(f"👋 {member.name} đã rời **{guild.name}**.")
        except Exception:
            pass  # không để lỗi này làm crash bot

async def setup(bot: commands.Bot):
    await bot.add_cog(GoodbyeCog(bot))
