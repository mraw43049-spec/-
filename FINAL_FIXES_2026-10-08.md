# Final fixes — 2026-10-08

- Added the supplied `ruby_emojis.py` stub so the bot can import `ruby_emojis` and start when the real emoji-shop module is not present in this package.
- Mini-app leaderboard: the Points category is labeled `روب‌پوینت` instead of `گیفت روبی`.
- Mini-app Education leaderboard: fixed the missing/empty user list by using a LEFT JOIN with `EducationProgress`, so users without an education row are also represented with 0 correct answers.
- Mini-app Education leaderboard now imports the education models through the existing lazy loader instead of referencing an undefined global module.
- `روباهیو درس` / `درس` / `آموزش روباهیو` is handled before other text flows, both in private chats and groups.
- Group `روباهیو درس` provides both a private-panel link and a direct Mini App Education button.
- Account recovery callback remains wired to `/account_recovery` and the `recovery:get` / `recovery:enter` callbacks; the supplied project code was kept and hardened around the command flow.
- Attack animation is now always `💣` instead of a random set of attack emojis.
- The supplied owl GIF was converted to an animated WebM sticker at 512×512 and compressed to about 189 KB: `assets/owl_sticker.webm`.
- Ruby Owl spawning now sends the new animated sticker, with the old `🦉` emoji as a safe fallback if the sticker file cannot be sent.

## Important deployment note

This package intentionally does not contain `config.py` or production secrets. Keep the existing `config.py` / Railway environment variables from the current deployment. Do not replace production database settings with dummy values.
