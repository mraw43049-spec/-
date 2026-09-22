# -*- coding: utf-8 -*-
"""فروشگاه شکلک روبی: خرید، انتخاب، انتقال و فروش مجدد با تأیید."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import User, RubyEmojiItem, get_session

CATEGORIES = {
    'flag': ('🏁', 150000, ['🇨🇦','🇺🇸','🇳🇴','🇮🇹','🇧🇷','🇬🇧','🇰🇷','🇱🇰','🏴‍☠️','🇦🇺','🇨🇵','🇩🇪','🇰🇵','🇮🇷','🇷🇺','🇲🇽','🇨🇳','🇦🇪','🇮🇱','🇦🇷','🇵🇹','🇳🇱','🇸🇪']),
    'light': ('💡', 100000, ['🕶','🪄','💅','💣','🪩','🪽','🎃','💰','⛓️‍','💊','🕯','🃏','⏳','🎈','💸','🪅']),
    'love': ('💘', 250000, ['💘','💖','💝','💙','💚','❤️','💍','💎','🎈','🎉','✨','🎁','🧸','🎀','💋']),
    'monster': ('🧟‍♀️', 200000, ['👼🏻','🧟‍♂️','🧟‍♀️','🧞‍♂️','🧞‍♀️','🦹‍♂️','🧚🏻‍♀️','🧜🏻‍♀️','🧌','🥷🏻','🦸🏻‍♂️','👨🏻‍💻','👽','🤖','👻','☠️','👺','🤡']),
    'nature': ('🍄', 120000, ['🌹','🌸','🌻','🍄','🐺','🐇','🦌','🐈','🐀','🐣','🐲','🐌','🦋','🕷','🦩','🌈','🌪','🔥','☀','⚡','☄️','🪐']),
    'fun': ('☢️', 180000, ['🍭','🍬','🍫','🍩','🥂🍾','🎂','🎮','👾','🎭','🎻','🏹','🏅','🎧','🛸','🚀','🎠','🔆','🫟','🍷','🧊','🧂','🍕','🍔','🫐','☢️']),
}

def _item_key(cat, idx): return f'{cat}:{idx}'
def _main_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton(f'{title} فروشگاه', callback_data=f'remoji:cat:{cat}')] for cat,(title,_,_) in CATEGORIES.items()])
def _grid(cat, owned):
    title, price, items=CATEGORIES[cat]; rows=[]
    row=[]
    for i,e in enumerate(items):
        mark='✅' if _item_key(cat,i) in owned else ''
        row.append(InlineKeyboardButton(f'{e}{mark}', callback_data=f'remoji:item:{cat}:{i}'))
        if len(row)==4: rows.append(row); row=[]
    if row: rows.append(row)
    rows.append([InlineKeyboardButton('🔙 برگشت', callback_data='remoji:home')])
    return InlineKeyboardMarkup(rows)

async def emoji_command(update, context):
    await update.message.reply_text('🛍 فروشگاه شکلک روبی\n\nیک بخش را انتخاب کن:', reply_markup=_main_kb())

async def emoji_callback(update, context):
    q=update.callback_query; parts=q.data.split(':'); s=get_session()
    try:
        u=s.get(User,q.from_user.id)
        if not u: return await q.answer('ابتدا ربات را استارت کن.', show_alert=True)
        owned={x.item_key for x in s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id).all()}
        if parts[1]=='home': return await q.edit_message_text('🛍 فروشگاه شکلک روبی\n\nیک بخش را انتخاب کن:', reply_markup=_main_kb())
        if parts[1]=='cat':
            cat=parts[2]; title,price,items=CATEGORIES[cat]
            return await q.edit_message_text(f'{title} بخش شکلک‌ها\n💰 قیمت هر خانه: {price:,} روب‌پوینت\nروی هر شکلک بزن:', reply_markup=_grid(cat,owned))
        cat,idx=parts[2],int(parts[3]); title,price,items=CATEGORIES[cat]; emoji=items[idx]; key=_item_key(cat,idx)
        item=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id,item_key=key).first()
        if item:
            kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ انتخاب برای نام', callback_data=f'remoji:select:{cat}:{idx}')],[InlineKeyboardButton('🎁 انتقال به کاربر', callback_data=f'remoji:transfer:{cat}:{idx}')],[InlineKeyboardButton('💸 فروش به ربات (نصف قیمت)', callback_data=f'remoji:sell:{cat}:{idx}')],[InlineKeyboardButton('🔙 برگشت', callback_data=f'remoji:cat:{cat}')]])
            return await q.edit_message_text(f'{emoji} این شکلک در انبار توست.\nیکی از گزینه‌ها را انتخاب کن:', reply_markup=kb)
        kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ بله، خرید', callback_data=f'remoji:buyyes:{cat}:{idx}'),InlineKeyboardButton('❌ خیر', callback_data=f'remoji:buyno:{cat}:{idx}')],[InlineKeyboardButton('🔙 برگشت', callback_data=f'remoji:cat:{cat}')]])
        return await q.edit_message_text(f'🛒 خرید {emoji}\n💰 قیمت: {price:,} روب‌پوینت\nآیا مطمئنی؟', reply_markup=kb)
    finally: s.close()

async def emoji_action(update, context):
    q=update.callback_query; parts=q.data.split(':'); action=parts[1]; cat=parts[2]; idx=int(parts[3]); title,price,items=CATEGORIES[cat]; emoji=items[idx]; key=_item_key(cat,idx); s=get_session()
    try:
        u=s.get(User,q.from_user.id)
        if not u: return await q.answer('کاربر پیدا نشد.',show_alert=True)
        if action=='transferyes' or action=='transferno':
            data=context.user_data.get('emoji_transfer_confirm')
            if action=='transferno' or not data: context.user_data.pop('emoji_transfer_confirm',None); return await q.edit_message_text('❌ انتقال لغو شد.')
            item=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id,item_key=data['key']).first()
            target=s.get(User,int(data['target_id']))
            if not item or not target: return await q.answer('شکلک یا کاربر مقصد پیدا نشد.',show_alert=True)
            item.owner_id=target.telegram_id
            if u.name_emoji==data['emoji']: u.name_emoji=''
            s.commit(); context.user_data.pop('emoji_transfer_confirm',None)
            return await q.edit_message_text(f'✅ {data["emoji"]} با موفقیت منتقل شد.')
        if action=='buyno':
            return await q.edit_message_text('❌ خرید لغو شد.')
        if action=='buyyes':
            if int(u.fox_points or 0)<price: return await q.answer('روب‌پوینت کافی نیست.',show_alert=True)
            if not s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id,item_key=key).first():
                u.fox_points-=price; s.add(RubyEmojiItem(owner_id=u.telegram_id,item_key=key,emoji=emoji,category=cat)); s.commit()
            return await q.edit_message_text(f'✅ {emoji} با موفقیت خریداری شد.\nمی‌توانی آن را انتخاب کنی تا کنار نامت نمایش داده شود.')
        if action=='select':
            if not s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id,item_key=key).first(): return await q.answer('این شکلک در انبارت نیست.',show_alert=True)
            u.name_emoji=emoji; s.commit(); return await q.edit_message_text(f'✅ شکلک {emoji} برای نامت انتخاب شد و از این به بعد در نمایش‌های روبی استفاده می‌شود.')
        if action=='sell':
            item=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id,item_key=key).first()
            if not item: return await q.answer('این شکلک در انبارت نیست.',show_alert=True)
            kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ بله، بفروش', callback_data=f'remoji:sellyes:{cat}:{idx}'),InlineKeyboardButton('❌ خیر', callback_data=f'remoji:item:{cat}:{idx}')]])
            return await q.edit_message_text(f'فروش {emoji} به ربات با قیمت {price//2:,} روب‌پوینت انجام شود؟',reply_markup=kb)
        if action=='sellyes':
            item=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id,item_key=key).first()
            if not item: return await q.answer('این شکلک در انبارت نیست.',show_alert=True)
            s.delete(item); u.fox_points+=price//2
            if u.name_emoji==emoji: u.name_emoji=''
            s.commit(); return await q.edit_message_text(f'✅ {emoji} فروخته شد و {price//2:,} روب‌پوینت دریافت کردی.')
        if action=='transfer':
            context.user_data['emoji_transfer']={'key':key,'cat':cat,'idx':idx,'emoji':emoji}
            return await q.edit_message_text(f'🎁 برای انتقال {emoji} آیدی عددی یا @شناسه کاربر مقصد را در پیام بعدی بفرست.')
    finally: s.close()

async def emoji_transfer_text(update, context):
    data=context.user_data.get('emoji_transfer')
    if not data: return False
    s=get_session()
    try:
        sender=s.get(User,update.effective_user.id); raw=(update.message.text or '').strip(); target=None
        if raw.startswith('@'):
            target=s.query(User).filter(User.username.ilike(raw[1:])).first()
        elif raw.isdigit(): target=s.get(User,int(raw))
        if not sender or not target: await update.message.reply_text('❌ کاربر مقصد پیدا نشد. آیدی عددی یا @شناسه درست بفرست.'); return True
        item=s.query(RubyEmojiItem).filter_by(owner_id=sender.telegram_id,item_key=data['key']).first()
        if not item: await update.message.reply_text('❌ این شکلک در انبار تو نیست.'); return True
        data['target_id']=target.telegram_id
        context.user_data['emoji_transfer_confirm']=data
        await update.message.reply_text(f'آیا از انتقال {data["emoji"]} به {target.username or target.telegram_id} مطمئنی؟', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('✅ بله', callback_data=f'remoji:transferyes:{data["cat"]}:{data["idx"]}'), InlineKeyboardButton('❌ خیر', callback_data=f'remoji:transferno:{data["cat"]}:{data["idx"]}')]]))
        return True
    finally: s.close()
