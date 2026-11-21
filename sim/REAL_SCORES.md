# Real scores (ground truth for calibration)

The real scorer is deterministic: the same bot gives the same score.

| bot | description | real score (48 matches) | simulator score (n, SE) | commit |
| --- | --- | --- | --- | --- |
| starter | Kit example bot (`kit/python/example_bot.py`) | 1.15 | 2.396 (48, 0.486) | kit |
| v1 | `bot_v1.py` / `bot.py` with `legacy_strategy=True` | 1.85 | 2.583 (48, 0.521) | likely `c3c5c1198b44d9b55eb4af5909ee04f2abf75a5f` |
| E | v2 all switches on, roofs on, `react_unseen` on | 1.25 | 1.438 (48, 0.289)* | likely `26d3d62ccd136ff09a30257ed970da13f7cd79d8` |
| F | E with `roofs=False` | 0.92 | ? (not simulated before the real score was known; not held out) | likely `7c6c20a1235bb94c52ecb51e89bf56ab573d2f90` |
| G | E with `roofs`, `hideouts`, `selective_fire` off | 1.25 | ? (not simulated before the real score was known; not held out) | ? |
| H | E with `react_unseen=False` | PENDING | ? | ? |
| v1-evade | v1 + evade-unseen (in `bot_v1.py`) | 2.10 | 3.250 (48, 0.591); not predicted before submission with a calibrated sim | `1b0732a7df648c46a5ff6acbef5048d6e36a2e9b` |

Known simulator numbers, all over 48 seeds starting at seed 1, with the older, uncalibrated
house-bot knobs: starter 2.396 (SE 0.486); v1 2.583 (SE 0.521); v2 all-on 1.438 (SE 0.289).
The order of the bots matches the real scorer, but the level is too high (the simulator's house
bots are too easy).

\* The v2 all-on simulator run predates the `react_unseen` patch, so it is not exactly bot E.
