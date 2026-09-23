# Education cert thresholds + support ID button

- Education certificate thresholds changed from 50*3^n to a growing sequence
  starting 10, 15, 25 and then each step = sum of the previous two:
  10, 15, 25, 40, 65, 105, 170, 275, 445, 720, 1165, 1885, 3050, 4935, 7985.
- Support menu now shows two buttons: "ارسال تیکت" (unchanged ticket flow)
  and a new "آیدی پشتیبانی" button that opens @escotch's chat directly via
  a Telegram URL button (no bot logic needed, Telegram handles the deep link).
- Ticket flow already confirmed to the user and sent to admins; left as-is.
