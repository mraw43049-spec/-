# Education cert thresholds + support ID button + admin ticket fix

- Education certificate thresholds (cumulative total correct answers needed):
  10, 15, 25, 40, 63, 95, 135, 183, 239, 304, 377, 458, 547, 645, 750.
  Starts 10/15/25 as requested, grows smoothly, last (15th) cert = 750 total
  correct answers (not thousands).
- Support menu shows two buttons: "ارسال تیکت" (ticket flow) and
  "آیدی پشتیبانی" (opens @escotch's chat directly via a Telegram URL button).
- FIX: admins could not submit their own support ticket, because
  admin_message_router ran before support_text in handler group 0 and PTB
  only runs the first matching handler per group, so an admin's ticket text
  was silently swallowed. Fixed by having admin_message_router fall back to
  support_text when nothing else matches, and removing the "admins can never
  submit a ticket" exclusion from support_text.
