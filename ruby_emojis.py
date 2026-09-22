# -*- coding: utf-8 -*-
"""فروشگاه و انبار شکلک روبی با ظرفیت، انتقال و فروش امن."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import User, RubyEmojiItem, get_session

TRANSFER_FEE = 25_000
STORAGE_UPGRADE_COST = 100_000
STORAGE_UPGRADE_SLOTS = 3
CATEGORIES = {
 'flag':('🏁',150000,['🇨🇦','🇺🇸','🇳🇴','🇮🇹','🇧🇷','🇬🇧','🇰🇷','🇱🇰','🏴‍☠️','🇦🇺','🇨🇵','🇩🇪','🇰🇵','🇮🇷','🇷🇺','🇲🇽','🇨🇳','🇦🇪','🇮🇱','🇦🇷','🇵🇹','🇳🇱','🇸🇪']),
 'light':('💡',100000,['🕶','🪄','💅','💣','🪩','🪽','🎃','💰','⛓️‍','💊','🕯','🃏','⏳','🎈','💸','🪅']),
 'love':('💘',250000,['💘','💖','💝','💙','💚','❤️','💍','💎','🎈','🎉','✨','🎁','🧸','🎀','💋']),
 'monster':('🧟‍♀️',200000,['👼🏻','🧟‍♂️','🧟‍♀️','🧞‍♂️','🧞‍♀️','🦹‍♂️','🧚🏻‍♀️','🧜🏻‍♀️','🧌','🥷🏻','🦸🏻‍♂️','👨🏻‍💻','👽','🤖','👻','☠️','👺','🤡']),
 'nature':('🍄',120000,['🌹','🌸','🌻','🍄','🐺','🐇','🦌','🐈','🐀','🐣','🐲','🐌','🦋','🕷','🦩','🌈','🌪','🔥','☀','⚡','☄️','🪐']),
 'fun':('☢️',180000,['🍭','🍬','🍫','🍩','🥂','🍾','🎂','🎮','👾','🎭','🎻','🏹','🏅','🎧','🛸','🚀','🎠','🔆','🫟','🍷','🧊','🧂','🍕','🍔','🫐','☢️'])}

def key(cat,idx): return f'{cat}:{idx}'
def main_kb():
 rows=[[InlineKeyboardButton(f'{t} فروشگاه',callback_data=f'remoji:cat:{c}')] for c,(t,_,_) in CATEGORIES.items()]
 rows += [[InlineKeyboardButton('📦 انبار شکلک‌ها',callback_data='remoji:storage:0')]]
 return InlineKeyboardMarkup(rows)
def grid(cat,owned):
 t,p,items=CATEGORIES[cat]; rows=[]; row=[]
 for i,e in enumerate(items):
  row.append(InlineKeyboardButton(f'{e}{"✅" if key(cat,i) in owned else ""}',callback_data=f'remoji:item:{cat}:{i}'))
  if len(row)==4: rows.append(row); row=[]
 if row: rows.append(row)
 rows.append([InlineKeyboardButton('🔙 برگشت',callback_data='remoji:home:0')]); return InlineKeyboardMarkup(rows)
def storage_kb(items):
 rows=[]
 for it in items:
  cat,idx=it.item_key.split(':'); rows.append([InlineKeyboardButton(f'{it.emoji}',callback_data=f'remoji:item:{cat}:{idx}')])
 rows += [[InlineKeyboardButton('⬆️ ارتقای ظرفیت (۱۰۰٬۰۰۰)',callback_data='remoji:upgrade:0')],[InlineKeyboardButton('🔙 برگشت',callback_data='remoji:home:0')]]
 return InlineKeyboardMarkup(rows)
async def emoji_command(update,context):
 await update.message.reply_text('🛍 ایموجی روبی\n\nیک بخش را انتخاب کن:',reply_markup=main_kb())
async def emoji_callback(update,context):
 q=update.callback_query; parts=q.data.split(':'); s=get_session()
 try:
  u=s.get(User,q.from_user.id)
  if not u: return await q.answer('ابتدا ربات را استارت کن.',show_alert=True)
  owned={x.item_key for x in s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id).all()}
  if parts[1]=='home': return await q.edit_message_text('🛍 ایموجی روبی\n\nیک بخش را انتخاب کن:',reply_markup=main_kb())
  if parts[1]=='storage':
   items=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id).all(); cap=u.emoji_storage_capacity or 3
   return await q.edit_message_text(f'📦 انبار شکلک‌ها\nظرفیت: {len(items)}/{cap}\nبرای ارتقا ۱۰۰٬۰۰۰ روب‌پوینت پرداخت کن.',reply_markup=storage_kb(items))
  if parts[1]=='cat':
   cat=parts[2]; t,p,items=CATEGORIES[cat]; return await q.edit_message_text(f'{t} بخش شکلک‌ها\n💰 قیمت: {p:,} روب‌پوینت',reply_markup=grid(cat,owned))
  cat,idx=parts[2],int(parts[3]); t,p,items=CATEGORIES[cat]; e=items[idx]; k=key(cat,idx)
  item=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id,item_key=k).first()
  if item:
   kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ انتخاب',callback_data=f'remoji:select:{cat}:{idx}')],[InlineKeyboardButton('🎁 انتقال',callback_data=f'remoji:transfer:{cat}:{idx}')],[InlineKeyboardButton('💸 فروش نصف قیمت',callback_data=f'remoji:sell:{cat}:{idx}')],[InlineKeyboardButton('🔙 برگشت',callback_data=f'remoji:cat:{cat}')]])
   return await q.edit_message_text(f'{e} در انبار توست.',reply_markup=kb)
  kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ بله، خرید',callback_data=f'remoji:buyyes:{cat}:{idx}'),InlineKeyboardButton('❌ خیر',callback_data=f'remoji:buyno:{cat}:{idx}')],[InlineKeyboardButton('🔙 برگشت',callback_data=f'remoji:cat:{cat}')]])
  return await q.edit_message_text(f'🛒 خرید {e}\n💰 قیمت: {p:,}\nآیا مطمئنی؟',reply_markup=kb)
 finally: s.close()
async def emoji_action(update,context):
 q=update.callback_query; parts=q.data.split(':'); action=parts[1]; s=get_session()
 try:
  u=s.get(User,q.from_user.id)
  if not u: return await q.answer('کاربر پیدا نشد.',show_alert=True)
  if action=='upgrade':
   if (u.fox_points or 0)<STORAGE_UPGRADE_COST: return await q.answer('روب‌پوینت کافی نیست.',show_alert=True)
   u.fox_points-=STORAGE_UPGRADE_COST; u.emoji_storage_capacity=(u.emoji_storage_capacity or 3)+3; s.commit(); return await q.edit_message_text(f'✅ ظرفیت انبار به {u.emoji_storage_capacity} رسید.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data='remoji:home:0')]]))
  cat,idx=parts[2],int(parts[3]); t,p,items=CATEGORIES[cat]; e=items[idx]; k=key(cat,idx)
  if action=='buyno': return await q.edit_message_text('❌ خرید لغو شد.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data='remoji:home:0')]]))
  if action=='buyyes':
   count=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id).count(); cap=u.emoji_storage_capacity or 3
   if count>=cap: return await q.answer('📦 انبار شکلک‌ها پر است؛ ارتقا بده یا شکلکی را بفروش.',show_alert=True)
   if (u.fox_points or 0)<p: return await q.answer('روب‌پوینت کافی نیست.',show_alert=True)
   u.fox_points-=p; s.add(RubyEmojiItem(owner_id=u.telegram_id,item_key=k,emoji=e,category=cat)); s.commit(); return await q.edit_message_text(f'✅ {e} خریداری شد.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data=f'remoji:cat:{cat}')]]))
  item=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id,item_key=k).first()
  if action=='select':
   if not item:return await q.answer('در انبار نیست.',show_alert=True)
   u.name_emoji=e; s.commit(); return await q.edit_message_text(f'✅ {e} انتخاب شد.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data=f'remoji:cat:{cat}')]]))
  if action=='sell':
   if not item:return await q.answer('در انبار نیست.',show_alert=True)
   kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ بله',callback_data=f'remoji:sellyes:{cat}:{idx}'),InlineKeyboardButton('❌ خیر',callback_data=f'remoji:item:{cat}:{idx}')]])
   return await q.edit_message_text(f'فروش {e} به مبلغ {p//2:,} روب‌پوینت؟',reply_markup=kb)
  if action=='sellyes':
   if not item:return await q.answer('در انبار نیست.',show_alert=True)
   s.delete(item); u.fox_points+=(p//2)
   if u.name_emoji==e:u.name_emoji=''
   s.commit(); return await q.edit_message_text(f'✅ {e} فروخته شد.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data=f'remoji:cat:{cat}')]]))
  if action=='transfer':
   context.user_data['emoji_transfer']={'key':k,'cat':cat,'idx':idx,'emoji':e}; return await q.edit_message_text(f'آیدی عددی یا @شناسه مقصد را بفرست.\nکارمزد انتقال: {TRANSFER_FEE:,} روب‌پوینت', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data='remoji:home:0')]]))
  if action in ('transferyes','transferno'):
   data=context.user_data.get('emoji_transfer_confirm')
   if action=='transferno' or not data: context.user_data.pop('emoji_transfer_confirm',None); return await q.edit_message_text('❌ لغو شد.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data='remoji:home:0')]]))
   item=s.query(RubyEmojiItem).filter_by(owner_id=u.telegram_id,item_key=data['key']).first(); target=s.get(User,int(data['target_id']))
   if not item or not target:return await q.answer('شکلک یا مقصد پیدا نشد.',show_alert=True)
   if (u.fox_points or 0)<TRANSFER_FEE:return await q.answer('برای انتقال ۲۵٬۰۰۰ روب‌پوینت لازم است.',show_alert=True)
   u.fox_points-=TRANSFER_FEE; item.owner_id=target.telegram_id
   if u.name_emoji==data['emoji']:u.name_emoji=''
   s.commit(); context.user_data.pop('emoji_transfer_confirm',None); 
   try:
    await context.bot.send_message(chat_id=target.telegram_id, text=f'🎁 یک شکلک روبی {data["emoji"]} از طرف کاربر {u.username or u.telegram_id} برایت ارسال شد!')
   except Exception: pass
   return await q.edit_message_text('✅ انتقال انجام شد.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data='remoji:home:0')]]))
 finally:s.close()
async def emoji_transfer_text(update,context):
 data=context.user_data.get('emoji_transfer')
 if not data:return False
 raw=(update.message.text or '').strip()
 if not (raw.isdigit() or raw.startswith('@')): return False
 s=get_session()
 try:
  sender=s.get(User,update.effective_user.id); target=None
  if raw.isdigit():target=s.get(User,int(raw))
  else: target=s.query(User).filter(User.username.ilike(raw[1:])).first()
  if not sender or not target:
   await update.message.reply_text('❌ کاربر مقصد پیدا نشد. آیدی عددی یا @شناسه درست بفرست.'); return True
  item=s.query(RubyEmojiItem).filter_by(owner_id=sender.telegram_id,item_key=data['key']).first()
  if not item: await update.message.reply_text('❌ این شکلک در انبار تو نیست.'); return True
  data['target_id']=target.telegram_id; context.user_data['emoji_transfer_confirm']=data
  await update.message.reply_text(f'آیا از انتقال {data["emoji"]} به {target.username or target.telegram_id} با کارمزد {TRANSFER_FEE:,} مطمئنی؟',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('✅ بله',callback_data=f'remoji:transferyes:{data["cat"]}:{data["idx"]}'),InlineKeyboardButton('❌ خیر',callback_data=f'remoji:transferno:{data["cat"]}:{data["idx"]}')],[InlineKeyboardButton('🔙 برگشت',callback_data='remoji:home:0')]])); return True
 finally:s.close()
