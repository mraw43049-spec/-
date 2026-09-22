# Fixes: bomb payout, support tickets, education cooldown

- Bomb cashout now credits the original entry amount plus the accumulated reward (e.g. 50,000 + 2,000 = 52,000).
- Completing all safe cells also credits entry plus accumulated reward.
- Support tickets are queued internally, sent to all configured ADMIN_IDS without Markdown parsing, and replies can be sent by replying to the admin ticket message.
- Users receive an explicit ticket confirmation even when delivery is temporarily unavailable.
- Education cooldown changed from 30 minutes to 25 minutes.
