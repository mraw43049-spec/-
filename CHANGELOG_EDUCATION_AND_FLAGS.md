# Education and flags patch

- Added confirmation before unlocking paid education topics (30,000 Rub Points).
- Education uses five topics with three-choice questions, 15-second answer window, and a 30-minute cooldown.
- Correct answers award 2 units and track answer count separately; certificate thresholds are 50 × 3^current_certificates.
- Certificate confirmation charges tuition (50,000 + 20,000 per prior certificate) and grants reward (150,000 + 50,000 per prior certificate).
- Added certificate progress to the Rubam/Robash profile display.
- Added 30 country flags with a selectable flag command; selected flag is stored and included by the shared display-name helper.
- Added safe database migrations for `name_flag`, `correct_answers`, and `pending_certificate` without deleting existing data.
