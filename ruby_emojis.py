"""سیستم ۷ گیفت روبی به‌صورت Custom Emoji واقعی تلگرام.

خود فایل‌های تصویری فقط برای ساخت پک تلگرام استفاده می‌شوند؛ نمایش نهایی کنار نام
از custom_emoji_id / Emoji Status تلگرام انجام می‌شود و عکسِ معمولی نیست.
"""
import json, logging, os, re
from pathlib import Path
from datetime import datetime, timezone
import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import MessageEntityType
from telegram import MessageEntity

from database import User, RubyEmojiItem, RubyEmojiCatalog, get_session

log = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DEFAULT_PRICE = int(os.environ.get("RUBY_GIFT_PRICE", "2500") or 2500)
PACK_TITLE = os.environ.get("RUBY_GIFT_PACK_TITLE", "گیفت روبی 🪄")

GIFT_CATALOG = {
    "ruby_blue":    {"title": "گیفت روبی آبی", "emoji": "🔵", "asset": "ruby_blue.webp"},
    "ruby_purple":  {"title": "گیفت روبی بنفش", "emoji": "🟣", "asset": "ruby_purple.webp"},
    "ruby_cyan":    {"title": "گیفت روبی فیروزه‌ای", "emoji": "🔷", "asset": "ruby_cyan.webp"},
    "ruby_gold":    {"title": "گیفت روبی طلایی", "emoji": "🟡", "asset": "ruby_gold.webp"},
    "ruby_red":     {"title": "گیفت روبی قرمز", "emoji": "🔴", "asset": "ruby_red.webp"},
    "ruby_ice":     {"title": "گیفت روبی یخی", "emoji": "⚪", "asset": "ruby_ice.webp"},
    "ruby_checker": {"title": "گیفت روبی شطرنجی", "emoji": "⚫", "asset": "ruby_checker.webp"},
}
CATEGORIES = {"gifts": ("🎁", "گیفت‌های روبی", list(GIFT_CATALOG.keys()))}


def _catalog_sync(session):
    for key, spec in GIFT_CATALOG.items():
        row = session.get(RubyEmojiCatalog, key)
        if row is None:
            row = RubyEmojiCatalog(item_key=key, title=spec["title"], price=DEFAULT_PRICE,
                                   fallback_emoji=spec["emoji"], active=1)
            session.add(row)
        else:
            row.title = spec["title"]
            row.fallback_emoji = spec["emoji"]
            if not row.price:
                row.price = DEFAULT_PRICE
    session.commit()


def _row(session, key):
    return session.get(RubyEmojiCatalog, key)


def _owned(session, uid, key):
    return session.query(RubyEmojiItem).filter_by(owner_id=uid, item_key=key).first()


def _active_key(user):
    return getattr(user, "name_emoji_item_key", None) or None


def _custom_id_for(session, key):
    row = _row(session, key)
    return str(row.custom_emoji_id) if row and row.custom_emoji_id else None


def _label(session, key):
    row = _row(session, key)
    if not row:
        return "🎁 گیفت روبی"
    return f"{row.fallback_emoji} {row.title}"


def _button(label, data, custom_id=None):
    if custom_id:
        try:
            return InlineKeyboardButton(label, callback_data=data, icon_custom_emoji_id=str(custom_id))
        except TypeError:
            pass
    return InlineKeyboardButton(label, callback_data=data)


def _home_keyboard(session, uid):
    rows=[]
    for key in GIFT_CATALOG:
        row=_row(session,key); owned=_owned(session,uid,key)
        icon_id=row.custom_emoji_id if row else None
        mark=" ✅ فعال" if owned and getattr(session.get(User,uid),'name_emoji_item_key',None)==key else ""
        rows.append([_button(f"{row.title}{mark} — {row.price:,}", f"remoji:item:{key}:{uid}", icon_id)])
    rows.append([InlineKeyboardButton("📦 کمد گیفت‌های من", callback_data=f"remoji:storage:{uid}")])
    return InlineKeyboardMarkup(rows)


def _item_keyboard(session, user, key):
    row=_row(session,key); owned=_owned(session,user.telegram_id,key)
    active=_active_key(user)==key
    rows=[]
    if not owned:
        rows.append([_button(f"🛒 خرید — {row.price:,} گیفت روبی", f"remoji:buyyes:{key}:{user.telegram_id}", row.custom_emoji_id)])
    elif active:
        rows.append([InlineKeyboardButton("🔴 غیرفعال کردن کنار نام", callback_data=f"remoji:select:{key}:{user.telegram_id}")])
    else:
        rows.append([_button("🟢 فعال کردن کنار نام", f"remoji:select:{key}:{user.telegram_id}", row.custom_emoji_id)])
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data=f"remoji:home:{user.telegram_id}")])
    return InlineKeyboardMarkup(rows)


def _item_text(session, user, key):
    row=_row(session,key); owned=_owned(session,user.telegram_id,key); active=_active_key(user)==key
    status="❌ نخریدی"
    if owned: status="🟢 فعال کنار نام" if active else "📦 در کمد"
    return (f"🎁 <b>{row.title}</b>\n\n"
            f"💰 قیمت: {row.price:,} گیفت روبی\n"
            f"📦 وضعیت: {status}\n\n"
            "بعد از فعال‌سازی، از Mini App می‌تونی همین Custom Emoji واقعی تلگرام رو به‌عنوان وضعیت کنار نامت هم تنظیم کنی.")


async def emoji_command(update, context):
    if not update.message: return
    s=get_session()
    try:
        u=s.get(User,update.effective_user.id)
        if not u:
            return await update.message.reply_text("اول /start رو بزن.")
        _catalog_sync(s)
        await update.message.reply_text("🎁 <b>گیفت روبی</b>\n\nیکی از گیفت‌ها رو انتخاب کن:",
            reply_markup=_home_keyboard(s,u.telegram_id), parse_mode="HTML", **({} if update.message.chat_id else {}))
    finally: s.close()


async def emoji_callback(update, context):
    q=update.callback_query; parts=q.data.split(":")
    s=get_session()
    try:
        u=s.get(User,q.from_user.id)
        if not u: return await q.answer("ابتدا /start را بزن.",show_alert=True)
        _catalog_sync(s)
        if parts[1] == "home":
            await q.edit_message_text("🎁 <b>گیفت روبی</b>\n\nانتخاب کن:",reply_markup=_home_keyboard(s,u.telegram_id),parse_mode="HTML"); return
        if parts[1] == "storage":
            items=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id).all()
            if not items:
                await q.edit_message_text("📦 کمد گیفتت خالیه.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data=f"remoji:home:{u.telegram_id}")]])); return
            lines=["📦 <b>کمد گیفت‌های من</b>",""]
            for it in items:
                lines.append(("🟢 " if _active_key(u)==it.item_key else "⚪ ")+_label(s,it.item_key))
            await q.edit_message_text("\n".join(lines),reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data=f"remoji:home:{u.telegram_id}")]]),parse_mode="HTML"); return
        if parts[1] == "item":
            key=parts[2]
            if key not in GIFT_CATALOG: return await q.answer("گیفت نامعتبره.",show_alert=True)
            await q.edit_message_text(_item_text(s,u,key),reply_markup=_item_keyboard(s,u,key),parse_mode="HTML"); return
        if parts[1] == "buyyes":
            key=parts[2]
            if key not in GIFT_CATALOG: return await q.answer("گیفت نامعتبره.",show_alert=True)
            row=_row(s,key)
            if _owned(s,u.telegram_id,key): return await q.answer("این گیفت رو قبلاً خریدی.",show_alert=True)
            if int(u.fox_points or 0) < int(row.price): return await q.answer(f"گیفت روبی کافی نداری؛ {row.price:,} لازمه.",show_alert=True)
            # اتمیک در همان تراکنش: کم‌کردن موجودی + مالکیت
            u.fox_points=int(u.fox_points or 0)-int(row.price)
            s.add(RubyEmojiItem(owner_id=u.telegram_id,item_key=key,emoji=row.fallback_emoji,category="gifts",custom_emoji_id=row.custom_emoji_id))
            s.commit()
            await q.answer("🎁 خرید انجام شد!")
            await q.edit_message_text(_item_text(s,u,key),reply_markup=_item_keyboard(s,u,key),parse_mode="HTML"); return
        if parts[1] == "select":
            key=parts[2]
            if key not in GIFT_CATALOG: return await q.answer("گیفت نامعتبره.",show_alert=True)
            if _active_key(u)==key:
                u.name_emoji_item_key=None; u.name_emoji_custom_id=None; u.name_emoji=''
                s.commit(); await q.answer("گیفت کنار نامت غیرفعال شد.");
            else:
                item=_owned(s,u.telegram_id,key)
                if not item: return await q.answer("اول این گیفت رو بخر.",show_alert=True)
                row=_row(s,key)
                u.name_emoji_item_key=key; u.name_emoji_custom_id=str(row.custom_emoji_id) if row.custom_emoji_id else None; u.name_emoji=row.fallback_emoji
                s.commit(); await q.answer("🟢 گیفت برای نامت فعال شد؛ برای نمایش به‌عنوان وضعیت تلگرام از مینی‌اپ استفاده کن.")
            await q.edit_message_text(_item_text(s,u,key),reply_markup=_item_keyboard(s,u,key),parse_mode="HTML"); return
        await q.answer()
    finally: s.close()


async def emoji_action(update, context):
    return await emoji_callback(update, context)


async def emoji_transfer_text(update, context):
    return False


def _utf16_len(text):
    return len(text.encode("utf-16-le"))//2


def custom_emoji_entity(text, custom_id, marker="🎁"):
    if not custom_id: return text, []
    idx=text.find(marker)
    if idx < 0: return text, []
    off=_utf16_len(text[:idx]); ln=_utf16_len(marker)
    return text, [MessageEntity(type=MessageEntityType.CUSTOM_EMOJI, offset=off, length=ln, custom_emoji_id=str(custom_id))]


def user_gift_data(session, uid):
    u=session.get(User,uid)
    if not u: return None
    key=getattr(u,'name_emoji_item_key',None)
    row=_row(session,key) if key else None
    return {"item_key":key,"custom_emoji_id":str(getattr(u,'name_emoji_custom_id',None) or (row.custom_emoji_id if row else '') or '') or None,
            "fallback_emoji":getattr(u,'name_emoji', '') or (row.fallback_emoji if row else '') or '🎁',
            "title":row.title if row else None}


def catalog_json(session):
    _catalog_sync(session)
    return [{"key":k,"title":r.title,"price":int(r.price),"custom_emoji_id":str(r.custom_emoji_id) if r.custom_emoji_id else None,"fallback_emoji":r.fallback_emoji}
            for k in GIFT_CATALOG if (r:=_row(session,k)) and r.active]


async def ensure_ruby_gift_pack(bot):
    """یک بار پک Custom Emoji واقعی را می‌سازد/می‌خواند و IDها را در DB می‌ریزد."""
    if os.environ.get("RUBY_GIFT_AUTO_SETUP","1").lower() not in {"1","true","yes","on"}:
        return
    try:
        me=await bot.get_me()
        safe=re.sub(r"[^a-zA-Z0-9]", "", me.username or "rubyfoxbot").lower() or "rubyfoxbot"
        pack=f"ruby_gifts_by_{safe}"
        owner_raw=os.environ.get("RUBY_GIFT_OWNER_ID","").strip()
        if owner_raw: owner=int(owner_raw)
        else:
            try:
                from config import ADMIN_IDS
                owner=int(sorted(ADMIN_IDS)[0])
            except Exception:
                return
        base=f"https://api.telegram.org/bot{BOT_TOKEN}"
        async with httpx.AsyncClient(timeout=40) as client:
            r=await client.get(f"{base}/getStickerSet",params={"name":pack})
            if r.status_code==200 and r.json().get("ok"):
                data=r.json()["result"]
            else:
                stickers=[]
                for key,spec in GIFT_CATALOG.items():
                    path=BASE_DIR/'assets'/'ruby_gifts'/spec['asset']
                    with open(path,'rb') as f:
                        up=await client.post(f"{base}/uploadStickerFile",data={"user_id":str(owner),"sticker_format":"static"},files={"sticker":(spec['asset'],f,'image/webp')})
                    uj=up.json()
                    if not uj.get('ok'): raise RuntimeError(f"uploadStickerFile failed for {key}: {uj}")
                    fid=uj['result']['file_id']
                    stickers.append({"sticker":fid,"format":"static","emoji_list":[spec['emoji']]})
                cr=await client.post(f"{base}/createNewStickerSet",data={
                    "user_id":str(owner),"name":pack,"title":PACK_TITLE,
                    "stickers":json.dumps(stickers,separators=(',',':'),ensure_ascii=False),
                    "sticker_type":"custom_emoji","needs_repainting":"false"})
                cj=cr.json()
                if not cj.get('ok'):
                    # another concurrent startup may have created it
                    gr=await client.get(f"{base}/getStickerSet",params={"name":pack})
                    gj=gr.json()
                    if not gj.get('ok'): raise RuntimeError(f"createNewStickerSet failed: {cj}")
                    data=gj['result']
                else:
                    gr=await client.get(f"{base}/getStickerSet",params={"name":pack})
                    gj=gr.json()
                    if not gj.get('ok'): raise RuntimeError(f"getStickerSet after create failed: {gj}")
                    data=gj['result']
            by_emoji={}
            for st in data.get('stickers') or []:
                cid=st.get('custom_emoji_id')
                alt=st.get('emoji') or ''
                if cid: by_emoji[alt]=str(cid)
            s=get_session()
            try:
                _catalog_sync(s)
                for key,spec in GIFT_CATALOG.items():
                    row=_row(s,key)
                    cid=by_emoji.get(spec['emoji'])
                    if cid:
                        row.custom_emoji_id=cid; row.pack_name=pack
                s.commit()
            finally: s.close()
        log.info("Ruby Gift Custom Emoji pack ready: %s",pack)
    except Exception:
        log.exception("Could not ensure Ruby Gift custom emoji pack")
