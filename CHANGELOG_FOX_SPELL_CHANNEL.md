# کانال آهنگ + «آیا منظورت ... بود؟» + غلط‌گیر املایی
- `fox_spell.py` (جدید، آفلاین): `suggest_command` (مقایسه‌ی آوایی گ/ک، ق/غ، ذ/ز/ض/ظ، ث/س/ص، ط/ت، ح/ه، ع/ا، پ/ب + فاصله‌ی ویرایشی)، `suggest_transfer`، `find_typos` (فهرست غلط‌های رایج + نسخه‌های غلطِ تولیدشده).
- `bot.py`:
  - `command_hint` / `spell_assist` / `spell_toggle_command` قبل از `ai_chat_entry` تو `text_router`.
  - کانال آهنگ: `mood_channel_member` (ثبت کانال وقتی ادمین ربات، ربات رو ادمین کانال می‌کنه)، `mood_channel_post` (آهنگ + هشتگ حال، ویرایش پست هم پوشش داده می‌شه)، دستور `کانال آهنگ [آیدی]`، متغیر `MOOD_CHANNEL_IDS`.
  - `purchase_flow_gate`: اگه آپدیت کاربر نداشت (پست کانال) برمی‌گرده.
  - `fox_mood_song_add` به `mood_song_upsert` منتقل شد (منطق مشترک بین دستور ادمین و کانال).
- `database.py`: ستون `group_chats.spell_mod` (migration خودکار) و جدول `fox_mood_channels`.
- متغیرهای اختیاری: `FOX_SPELL_DEFAULT` (پیش‌فرض 1)، `MOOD_CHANNEL_IDS`.
