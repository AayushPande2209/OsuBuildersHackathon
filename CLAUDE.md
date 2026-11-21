# Mech Royale bot: standing rules

## Goal
Maximise the official practice score: the mean of `16 - place` over 48 matches against
15 house bots that play as one squad, share vision and hunt this bot.

- Best real score so far: **1.85** (v1 behaviour; see `EXPERIMENTS.md` for the commit).
- Submission cutoff: **Sun 11:00 AM ET**. At most **4 submissions per hour**.
- The final round uses different seeds than the 48 practice seeds. Prefer changes with a
  clear mechanical reason (a failure seen in logs or replays) over blind parameter tweaks,
  so we do not overfit the practice seeds.

## How to change the bot
1. One change per submission, so every score is attributable.
2. Always branch from the best-scoring commit in `EXPERIMENTS.md`, never from a worse one.
3. If a submission scores below the best, revert to the best commit and record in
   `EXPERIMENTS.md` why it probably failed.
4. Use `scripts/make_variant.py` to flip `CONFIG` switches instead of hand-editing.

## Before proposing any submission
- Run `scripts/gate.sh`. It must pass. Submit only a clean, pushed commit; the 40-char hash
  pasted into the submit form must be exactly what `gate.sh` printed.
- If `sim/` exists: run the simulator for at least 200 matches on the candidate and on the best
  commit with identical seeds. Only propose the change if it beats the best by more than the
  combined standard error. If not, say so and explain why it is still worth a real submission
  (or don't submit it).

## Hard constraints on the bot
- Never delete or rewrite `bot_v1.py`: `bot.py` imports it even when `legacy_strategy` is off.
- No network at runtime. Standard library only.
- Under 15 ms per decision locally (the real limit is 50 ms on 1 CPU).
- Never crash: keep the exception fallback that returns a safe action.
- Keep stderr logging small (about one line every few seconds), and always log the mode, HP and
  damage source around deaths, so match logs can explain failures.

## Repo hygiene
- Keep the repo under 20 MB.
- Never commit `sim/out/`, replays, raw logs or `__pycache__`.
- `sim/`, scripts and docs stay out of the Docker image (`.dockerignore`).

## After every real score the user pastes
Update `EXPERIMENTS.md` (and `sim/REAL_SCORES.md` if present) **before doing anything else**.

## Honesty
Never report a score that was not measured. Label simulator numbers as simulator numbers, and
say clearly what is a guess. The real scorer is deterministic (same bot, same score), so a score
change on the practice seeds comes from the code change, not luck.
