# Experiment log

**Best so far: v1, 1.85** (behaviour of `bot_v1.py`; best known commit `c3c5c1198b44d9b55eb4af5909ee04f2abf75a5f` on `v2`, `legacy_strategy=True`)

Newest last. `?` = unknown. Commit hashes are only filled in when known; never guess them.

Known commits (from `git log`, which bot each one is):
- `c3c5c1198b44d9b55eb4af5909ee04f2abf75a5f` (`v2`): `legacy_strategy=True`, runs v1. Most likely the resubmission that scored 1.85 (not confirmed against the submit form).
- `26d3d62ccd136ff09a30257ed970da13f7cd79d8` (`v2` HEAD): patched v2, all switches on, roofs on, `react_unseen` on = E.
- `7c6c20a1235bb94c52ecb51e89bf56ab573d2f90` (`main` HEAD): E with `roofs=False` = F. Most likely the commit submitted as F (not confirmed against the submit form).

| # | date/time (ET) | commit (40 chars) | branch | what changed (one line) | hypothesis | sim score (n matches, SE) | real score | decision (keep/revert) | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ? | ? | ? | v1 baseline, first submission | General fighter with zone logic beats the starter | 2.583 (48, 0.521), uncalibrated sim | 1.85 | keep | A later resubmission of the same behaviour (likely `c3c5c11…`, `legacy_strategy=True`) also scored exactly 1.85, so the scorer is deterministic |
| 2 | 2026-11-20 ? | ? (likely `26d3d62ccd136ff09a30257ed970da13f7cd79d8`) | v2 | v2 all switches on, roofs on, `react_unseen` on (E) | Stealth, hideouts and roofs avoid the hunting squad | 1.438 (48, 0.289), pre-patch, uncalibrated sim | 1.25 | revert | Confirmed again (user re-reported 1.25). Probably failed because hiding and sitting still loses against a squad that hunts the bot using shared vision |
| 3 | ? | ? (likely `7c6c20a1235bb94c52ecb51e89bf56ab573d2f90`) | main | F: E with `roofs=False` | Roof climbs are the main cause of deaths | ? | 0.92 | revert | Worse than E (1.25), so roofs were not what hurt E; in v2 they helped by about 0.33. The loss against v1 (1.85) must come from the rest of v2 (stealth, hideouts, selective fire, slow quiet movement). F was not simulated before its score arrived, so it is no longer a held-out test for calibration |
| 4 | ? | ? | ? | G: E with `roofs`, `hideouts`, `selective_fire` off | Sitting in hideouts and holding fire is what hurts | ? | 1.25 | revert | Beats F (0.92) by 0.33, so hideouts plus holding fire cost about 0.33 (the two are not separated). Still 0.60 below v1: the remaining v2 parts (stealth/quiet_move 0.36, limited looting after 12 s, defensive upgrades, endgame waiting, evasion, react_unseen) together are worse than v1. Equal to E (1.25) by coincidence; scores are multiples of 1/48. Not simulated before the score arrived, so not held out |
| 5 | ? | ? | ? | H: E with `react_unseen=False` | Isolates the effect of the evade-unseen patch | ? | PENDING | ? | |
