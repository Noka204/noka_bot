# cogs/welcome.py
import os, json, re, asyncio
from datetime import datetime, timezone
import discord
from discord.ext import commands
from discord import app_commands

CONFIG = "config.json"
HEX = re.compile(r"^#(?:[0-9a-fA-F]{6})$")
EMBED_TAG = re.compile(r"\{embed:([^\}]+)\}", re.IGNORECASE)

# ================== CONFIG CACHE (tối ưu I/O) ==================
DEFAULT_CFG = {
    "welcome channel": None,        # ID text-channel gửi lời chào
    "welcome text": None,           # 1 câu chào; set lần nào cũng ghi đè
    "embeds": {},                   # kho embed theo tên
    "default assets channel": None  # kênh bot re-host ảnh (CDN Discord)
}

_CFG: dict | None = None
_CFG_LOCK = asyncio.Lock()
_SAVE_TASK: asyncio.Task | None = None
_DEBOUNCE_MS = 0.5  # gộp ghi file

def _load_cfg_from_disk() -> dict:
    if not os.path.exists(CONFIG):
        return DEFAULT_CFG.copy()
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        data = {}
    out = DEFAULT_CFG.copy()
    out.update(data)
    if not isinstance(out.get("embeds"), dict):
        out["embeds"] = {}
    return out

async def get_cfg() -> dict:
    global _CFG
    async with _CFG_LOCK:
        if _CFG is None:
            _CFG = _load_cfg_from_disk()
        return _CFG

async def _save_cfg_now():
    global _CFG
    async with _CFG_LOCK:
        data = _CFG or DEFAULT_CFG.copy()
        # ghi atomically
        tmp = CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG)

async def schedule_save_cfg():
    global _SAVE_TASK
    # debounce: gộp nhiều lần gọi trong 500ms
    if _SAVE_TASK and not _SAVE_TASK.done():
        return
    async def _runner():
        await asyncio.sleep(_DEBOUNCE_MS)
        await _save_cfg_now()
    _SAVE_TASK = asyncio.create_task(_runner())

async def set_cfg_mutate(mutator):
    """mutator(cfg) -> None; đảm bảo cache + debounce save."""
    global _CFG
    async with _CFG_LOCK:
        if _CFG is None:
            _CFG = _load_cfg_from_disk()
        mutator(_CFG)
    await schedule_save_cfg()

# ================== HELPERS ==================
def is_https_url(s: str | None) -> bool:
    if not s:
        return False
    s = s.strip()
    return s.startswith("https://") and len(s) <= 2048

def substitute_vars(s: str | None, *, user_mention: str, server_name: str) -> str | None:
    if not s:
        return None
    return s.replace("{user}", user_mention).replace("{server}", server_name)

def parse_embed_name_from_text(text: str) -> tuple[str | None, str]:
    """Trả về (embed_name, content_without_embed_tag)."""
    if not isinstance(text, str):
        return (None, "")
    m = EMBED_TAG.search(text)
    embed_name = m.group(1).strip() if m else None
    content = EMBED_TAG.sub("", text).strip()
    return embed_name, content

# ================== BUILD EMBED (tối ưu & an toàn) ==================
def _build_embed_from_template(tpl: dict, member: discord.Member | discord.User, guild: discord.Guild) -> discord.Embed:
    # màu
    col = (tpl.get("color") or "#00bcd4") if isinstance(tpl, dict) else "#00bcd4"
    try:
        color = discord.Color.from_str(col)
    except Exception:
        color = discord.Color.blurple()

    # biến
    server_name = guild.name
    user_mention = member.mention if isinstance(member, discord.Member) else getattr(member, "mention", f"@{getattr(member,'name','user')}")

    title = substitute_vars(tpl.get("title"), user_mention=user_mention, server_name=server_name)
    desc  = substitute_vars(tpl.get("description"), user_mention=user_mention, server_name=server_name)

    # Nếu cả title & desc đều rỗng → dùng zero-width space cho desc (tránh 400)
    if not title and not desc:
        desc = "\u200b"

    # KHÔNG truyền tham số rỗng vào constructor
    e = discord.Embed(color=color, timestamp=datetime.now(timezone.utc))
    if title:
        e.title = title
    if desc:
        e.description = desc

    thumb = tpl.get("thumbnail")
    if thumb == "avatar":
        av = getattr(member, "display_avatar", None) or getattr(member, "avatar", None)
        if av:
            e.set_thumbnail(url=av.url)
    elif isinstance(thumb, str) and is_https_url(thumb):
        e.set_thumbnail(url=thumb)

    img = tpl.get("image")
    if isinstance(img, str) and is_https_url(img):
        e.set_image(url=img)

    ft = substitute_vars(tpl.get("footer"), user_mention=user_mention, server_name=server_name)
    if ft:
        e.set_footer(text=ft)

    return e

def build_named_embed(name: str | None, member: discord.Member | discord.User, guild: discord.Guild, cfg: dict) -> discord.Embed | None:
    if not name:
        return None
    tpl = cfg.get("embeds", {}).get(name)
    if not isinstance(tpl, dict):
        return None
    return _build_embed_from_template(tpl, member, guild)

# ================== PANEL (1 message, edit-in-place) ==================
class CreateEmbedView(discord.ui.View):
    def __init__(self, author_id: int, name: str):
        super().__init__(timeout=600)  # 10 phút
        self.author_id = author_id
        self.name = name
        self.message_id: int | None = None
        self.channel_id: int | None = None

    def bind_message(self, message: discord.Message):
        self.message_id = message.id
        self.channel_id = message.channel.id

    async def fetch_message(self, itx: discord.Interaction) -> discord.Message | None:
        if not self.message_id or not self.channel_id:
            return None
        try:
            ch = itx.client.get_channel(self.channel_id) or await itx.client.fetch_channel(self.channel_id)
            return await ch.fetch_message(self.message_id)
        except Exception:
            return None

    async def refresh_panel(self, itx: discord.Interaction):
        cfg = await get_cfg()
        guild = itx.guild
        user = itx.user
        preview = build_named_embed(self.name, user, guild, cfg)

        # Nếu embed trống hoàn toàn → show placeholder để tránh 400
        if preview is None or (not preview.title and not preview.description and not preview.image and not preview.thumbnail):
            preview = discord.Embed(
                title="(Chưa có nội dung)",
                description="Nhấn các nút để thêm Title/Description/…",
                color=discord.Color.blurple()
            )

        tpl = cfg.get("embeds", {}).get(self.name, {}) or {}
        def short(v, l=70):
            s = str(v) if v is not None else ""
            return (s[:l] + "…") if len(s) > l else s

        img_val = tpl.get('image')
        thumb_val = tpl.get('thumbnail')
        img_show = "INVALID URL" if (isinstance(img_val, str) and img_val and not is_https_url(img_val)) else short(img_val)
        thumb_show = thumb_val
        if isinstance(thumb_val, str) and thumb_val not in (None, "", "avatar") and not is_https_url(thumb_val):
            thumb_show = "INVALID URL"

        content = "\n".join([
            f"**Embed:** `{self.name}`",
            f"• Title: `{short(tpl.get('title'))}`",
            f"• Description: `{short(tpl.get('description'))}`",
            f"• Color: `{tpl.get('color') or '#00bcd4'}`",
            f"• Image: `{img_show or ''}`",
            f"• Thumbnail: `{thumb_show or ''}`  (avatar/URL)",
            f"• Footer: `{short(tpl.get('footer'))}`",
            "(Panel sẽ tự khoá sau 10 phút không thao tác)"
        ])

        msg = await self.fetch_message(itx)
        if msg:
            await msg.edit(content=content, embed=preview, view=self)

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id == self.author_id or itx.user.guild_permissions.manage_guild:
            return True
        await itx.response.send_message("⛔ Chỉ người mở panel hoặc quản trị mới thao tác.", ephemeral=True, delete_after=3)
        return False

    # ----- Buttons & Modals -----
    @discord.ui.button(label="Tiêu đề", style=discord.ButtonStyle.primary, row=0)
    async def btn_title(self, itx: discord.Interaction, _):
        await itx.response.send_modal(_TextModal(self, "title", f"[{self.name}] Tiêu đề Embed", "Nhập tiêu đề"))

    @discord.ui.button(label="Mô tả", style=discord.ButtonStyle.primary, row=0)
    async def btn_desc(self, itx: discord.Interaction, _):
        ph = "Ví dụ: Xin chào {user}, chào mừng tới {server}!"
        await itx.response.send_modal(_TextModal(self, "description", f"[{self.name}] Mô tả Embed", "Nội dung", ph))

    @discord.ui.button(label="Màu (#RRGGBB)", style=discord.ButtonStyle.secondary, row=1)
    async def btn_color(self, itx: discord.Interaction, _):
        await itx.response.send_modal(_ColorModal(self))

    @discord.ui.button(label="Ảnh lớn (image URL)", style=discord.ButtonStyle.secondary, row=1)
    async def btn_image(self, itx: discord.Interaction, _):
        await itx.response.send_modal(_TextModal(self, "image", f"[{self.name}] Ảnh lớn", "URL (https://…)", "https://…"))

    @discord.ui.button(label="Thumbnail (avatar/URL)", style=discord.ButtonStyle.secondary, row=2)
    async def btn_thumb(self, itx: discord.Interaction, _):
        await itx.response.send_modal(_TextModal(self, "thumbnail", f"[{self.name}] Thumbnail", "avatar hoặc URL (https://…)", "avatar"))

    @discord.ui.button(label="Footer", style=discord.ButtonStyle.secondary, row=2)
    async def btn_footer(self, itx: discord.Interaction, _):
        await itx.response.send_modal(_TextModal(self, "footer", f"[{self.name}] Footer", "Nhập footer", "{server} chúc bạn vui vẻ!"))

    @discord.ui.button(label="Reload", style=discord.ButtonStyle.success, row=3)
    async def btn_reload(self, itx: discord.Interaction, _):
        await itx.response.defer()
        await self.refresh_panel(itx)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, row=3)
    async def btn_close(self, itx: discord.Interaction, _):
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                c.disabled = True
        await itx.response.defer()
        msg = await self.fetch_message(itx)
        if msg:
            await msg.edit(view=self)

class _TextModal(discord.ui.Modal):
    def __init__(self, view: "CreateEmbedView", field: str, title: str, label: str, placeholder: str = "", max_len: int = 4000):
        super().__init__(title=title, timeout=180)
        self._view = view
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
        val = (self.input.value or "").strip()
        cfg = await get_cfg()
        embeds = cfg.setdefault("embeds", {})
        tpl = embeds.setdefault(self._view.name, {})

        # URL validation cho image/thumbnail
        if self.field in ("image", "thumbnail"):
            if val.lower() == "avatar" and self.field == "thumbnail":
                tpl[self.field] = "avatar"
            elif val == "":
                tpl[self.field] = None
            elif not is_https_url(val):
                return await itx.response.send_message("⛔ URL phải là **https://** và ≤ 2048 ký tự.", ephemeral=True, delete_after=4)
            else:
                tpl[self.field] = val
        else:
            tpl[self.field] = val if val else None

        await set_cfg_mutate(lambda c: c)  # đánh dấu thay đổi để debounce save
        await itx.response.defer()
        await self._view.refresh_panel(itx)

class _ColorModal(discord.ui.Modal, title="Màu Embed (#RRGGBB)"):
    color = discord.ui.TextInput(label="Color", placeholder="#00bcd4", required=True, max_length=7)
    def __init__(self, view: "CreateEmbedView"):
        super().__init__()
        self._view = view
    async def on_submit(self, itx: discord.Interaction):
        val = str(self.color.value).strip()
        if not HEX.match(val):
            return await itx.response.send_message("⚠️ Sai định dạng. Dùng **#RRGGBB**.", ephemeral=True, delete_after=3)
        cfg = await get_cfg()
        cfg.setdefault("embeds", {}).setdefault(self._view.name, {})["color"] = val
        await set_cfg_mutate(lambda c: c)
        await itx.response.defer()
        await self._view.refresh_panel(itx)

# ================== CDN DISCORD (re-host ảnh) ==================
async def upload_to_assets_and_get_url(itx: discord.Interaction, att: discord.Attachment) -> str | None:
    if not att.content_type or not att.content_type.startswith("image/"):
        return None
    cfg = await get_cfg()
    ch_id = cfg.get("default assets channel")
    # fallback: kênh hiện tại (nếu không set asset channel)
    dest = itx.guild.get_channel(ch_id) if ch_id else itx.channel
    try:
        f = await att.to_file()
        # silent=True không ping ai; giữ message để URL sống
        msg = await dest.send(file=f, silent=True)
        if msg.attachments:
            return msg.attachments[0].url  # https://cdn.discordapp.com/...
    except Exception:
        return None
    return None

# ================== COG ==================
class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    group = app_commands.Group(
        name="welcome",
        description="Cấu hình welcome & embed"
    )

    # --- cấu hình cơ bản ---
    @group.command(name="set-channel", description="Chọn kênh gửi lời chào")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(self, itx: discord.Interaction, channel: discord.TextChannel):
        await set_cfg_mutate(lambda c: c.__setitem__("welcome channel", channel.id))
        await itx.response.send_message(f"✅ Welcome channel: {channel.mention}", ephemeral=True)

    @group.command(
        name="set-text",
        description="Đặt 1 câu chào (ghi đè mỗi lần). Hỗ trợ {user}, {server}, {embed:TÊN}"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_text(self, itx: discord.Interaction, text: str):
        text = (text or "").strip()
        if not text:
            return await itx.response.send_message("⚠️ Nội dung trống.", ephemeral=True)
        await set_cfg_mutate(lambda c: c.__setitem__("welcome text", text))

        m = EMBED_TAG.search(text)
        hint = ""
        if m:
            ename = m.group(1).strip()
            hint = f"\nℹ️ Có tag embed: `{ename}` → tạo/chỉnh bằng `/welcome create-embed name:{ename}`"
        await itx.response.send_message("✅ Đã lưu câu chào." + hint, ephemeral=True)

    # --- panel tạo/chỉnh embed ---
    @group.command(name="create-embed", description="Tạo/chỉnh một embed theo tên; dùng với {embed:TÊN} trong câu chào")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def create_embed(self, itx: discord.Interaction, name: str):
        name = name.strip()
        if not name:
            return await itx.response.send_message("⚠️ Tên embed trống.", ephemeral=True)

        async def _mut(c):
            embeds = c.setdefault("embeds", {})
            embeds.setdefault(name, {})
        await set_cfg_mutate(_mut)

        view = CreateEmbedView(itx.user.id, name)
        cfg = await get_cfg()
        preview = build_named_embed(name, itx.user, itx.guild, cfg)
        if preview is None or (not preview.title and not preview.description and not preview.image and not getattr(preview, "thumbnail", None)):
            preview = discord.Embed(
                title="(Chưa có nội dung)",
                description="Nhấn các nút để thêm Title/Description/…",
                color=discord.Color.blurple()
            )

        await itx.response.send_message(content=f"**Embed:** `{name}`", embed=preview, view=view)
        msg = await itx.original_response()
        view.bind_message(msg)
        await view.refresh_panel(itx)

    # --- assets / re-host ---
    @group.command(name="set-assets", description="Chọn kênh để bot lưu file ảnh (CDN Discord)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_assets(self, itx: discord.Interaction, channel: discord.TextChannel):
        await set_cfg_mutate(lambda c: c.__setitem__("default assets channel", channel.id))
        await itx.response.send_message(f"✅ Assets channel: {channel.mention}", ephemeral=True)

    @group.command(name="set-image-upload", description="Upload ảnh → set vào Image của embed theo tên (CDN Discord)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_image_upload(self, itx: discord.Interaction, name: str, file: discord.Attachment):
        url = await upload_to_assets_and_get_url(itx, file)
        if not url:
            return await itx.response.send_message("⛔ File phải là hình ảnh.", ephemeral=True)
        async def _mut(c):
            c.setdefault("embeds", {}).setdefault(name.strip(), {})["image"] = url
        await set_cfg_mutate(_mut)
        await itx.response.send_message(f"✅ Đã set **image** cho `{name}` bằng CDN Discord.", ephemeral=True)

    @group.command(name="set-thumb-upload", description="Upload ảnh → set vào Thumbnail của embed theo tên (CDN Discord)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_thumb_upload(self, itx: discord.Interaction, name: str, file: discord.Attachment):
        url = await upload_to_assets_and_get_url(itx, file)
        if not url:
            return await itx.response.send_message("⛔ File phải là hình ảnh.", ephemeral=True)
        async def _mut(c):
            c.setdefault("embeds", {}).setdefault(name.strip(), {})["thumbnail"] = url
        await set_cfg_mutate(_mut)
        await itx.response.send_message(f"✅ Đã set **thumbnail** cho `{name}` bằng CDN Discord.", ephemeral=True)

    # --- test ---
    @group.command(name="test", description="Gửi thử như có người mới vào (dùng đúng channel & text đã cấu hình)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(self, itx: discord.Interaction):
        cfg = await get_cfg()

        ch_id = cfg.get("welcome channel")
        dest = itx.guild.get_channel(ch_id) if ch_id else None
        if not isinstance(dest, discord.TextChannel):
            return await itx.response.send_message("⚠️ Chưa cấu hình `welcome channel`. Dùng `/welcome set-channel`.", ephemeral=True)

        text = cfg.get("welcome text")
        if not isinstance(text, str) or not text.strip():
            return await itx.response.send_message("📭 Chưa đặt `welcome text`. Dùng `/welcome set-text`.", ephemeral=True)

        target = itx.user
        embed_name, content = parse_embed_name_from_text(text)
        embed_obj = build_named_embed(embed_name, target, itx.guild, cfg) if embed_name else None
        if content:
            content = content.replace("{user}", target.mention).replace("{server}", itx.guild.name)

        try:
            await dest.send(content=content or None, embed=embed_obj)
            await itx.response.send_message(f"✅ Đã gửi thử vào {dest.mention}", ephemeral=True)
        except discord.Forbidden:
            await itx.response.send_message("⛔ Bot không có quyền gửi ở kênh này.", ephemeral=True)
        except Exception as ex:
            await itx.response.send_message(f"❌ Lỗi: {ex}", ephemeral=True)

    # --- sự kiện thật ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = await get_cfg()
        ch_id = cfg.get("welcome channel")
        if not ch_id:
            return
        channel = member.guild.get_channel(ch_id)
        if not isinstance(channel, discord.TextChannel):
            return

        text = cfg.get("welcome text")
        if not isinstance(text, str) or not text.strip():
            return

        embed_name, content = parse_embed_name_from_text(text)
        embed_obj = build_named_embed(embed_name, member, member.guild, cfg) if embed_name else None
        if content:
            content = content.replace("{user}", member.mention).replace("{server}", member.guild.name)

        try:
            await channel.send(content=content or None, embed=embed_obj)
        except Exception:
            pass  # không crash bot

async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
