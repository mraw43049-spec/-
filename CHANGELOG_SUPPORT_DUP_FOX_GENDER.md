# Fix duplicate support message + fox rename/gender feature

- FIX: "پشتیبانی" (and ticket replies) sent two identical messages. Cause:
  support_text was wired into THREE places — a direct group-0 MessageHandler,
  admin_message_router's fallback (group 0), and text_router (group 2) — so
  every message got processed twice (once in group 0, once in group 2).
  Fixed by removing the redundant direct group-0 registration and making
  admin_message_router raise ApplicationHandlerStop once it successfully
  handles something, so group 2 doesn't run again for the same update.
- Fox panel: the "✏️ تغییر اسم روباه" button is now just "✏️". Tapping it
  opens a small menu with two options: "🐾 تغییر نام روبی" and
  "⚧ تغییر جنسیت". Both flows end in a yes/no confirmation before anything
  is saved. Gender is male/female (♂️/♀️) and is now shown in the fox panel
  itself and in روبام/روباش. Added a new `fox_gender` DB column (auto-migrated
  on startup, defaults to unset/"نامشخص" for existing users).
