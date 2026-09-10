# بات بازی تلگرامی

بات تلگرامی که کاربر هر ۵ دقیقه با فرستادن یه کلمه کلیدی پوینت می‌گیره و با بالا رفتن سطح،
بازی‌های دونفره (تاس 🎲، دارت 🎯، بولینگ 🎳، فوتبال ⚽) براش باز میشه.

## ساختار پروژه

```
telegram_game_bot/
├── bot.py            # فایل اصلی و همه‌ی هندلرها
├── config.py         # خواندن متغیرهای محیطی
├── database.py       # مدل‌های SQLAlchemy (پستگرس)
├── game_logic.py      # منطق سطح‌بندی و آزادسازی بازی‌ها
├── requirements.txt
├── Procfile          # برای Railway
└── .env.example
```

## مراحل راه‌اندازی محلی

1. یه بات جدید توی [@BotFather](https://t.me/BotFather) بساز و توکنشو بگیر.
2. یه دیتابیس پستگرس بساز (لوکال یا روی Railway/Neon/Supabase).
3. پکیج‌ها رو نصب کن:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. فایل `.env.example` رو کپی کن به `.env` و مقادیر `BOT_TOKEN` و `DATABASE_URL` رو پر کن.
5. اجرا کن:
   ```bash
   python bot.py
   ```

## دیپلوی روی گیت‌هاب

```bash
git init
git add .
git commit -m "اولین نسخه بات بازی"
git branch -M main
git remote add origin <آدرس ریپازیتوری‌ت>
git push -u origin main
```

فایل `.gitignore` مطمئن میشه که `.env` (و توکن مخفیت) روی گیت‌هاب آپلود نشه.

## دیپلوی روی Railway

1. وارد [railway.app](https://railway.app) شو و یه پروژه جدید بساز.
2. گزینه‌ی "Deploy from GitHub repo" رو انتخاب کن و ریپازیتوری‌ت رو وصل کن.
3. توی همون پروژه، یه سرویس "PostgreSQL" هم اضافه کن (Add → Database → PostgreSQL).
4. Railway به‌صورت خودکار یه متغیر `DATABASE_URL` برای سرویس پستگرس می‌سازه.
   این متغیر رو کپی کن و توی تنظیمات سرویس بات (Variables) هم به اسم `DATABASE_URL` اضافه کن
   (یا با Reference Variable مستقیم وصلش کن).
5. متغیر `BOT_TOKEN` رو هم توی همون بخش Variables اضافه کن.
6. چون این بات با `run_polling()` کار می‌کنه (نه وب‌هوک)، Railway با همون `Procfile`
   (`worker: python bot.py`) بدون نیاز به تنظیم دامنه یا پورت اجرا میشه.
7. بعد از دیپلوی، لاگ‌ها رو چک کن تا مطمئن شی خط "Bot started polling..." رو دیدی.

## نکته درباره کلمه کلیدی

پیش‌فرض کلمه‌ی claim، «هور» هست. اگه می‌خوای عوضش کنی، فقط متغیر `CLAIM_KEYWORD`
رو توی `.env` (یا Variables توی Railway) تغییر بده.

## دستورات بات

- `/start` — شروع و ثبت‌نام
- `/profile` — دیدن پوینت، سطح و بازی‌های بازشده
- `/games` — لیست بازی‌های قابل‌بازی
- `/challenge <game>` — با ریپلای روی پیام یه نفر، دعوتش کن به بازی
  (مقادیر معتبر: `dice`, `darts`, `bowling`, `football`)
