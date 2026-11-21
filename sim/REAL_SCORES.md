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
| v1-roof | v1-evade + climb a roof and fight from it | 1.83 | 3.865 (200, 0.318) on the fixed sim, predicted +1.00 over v1-evade; real was -0.27 | `02e0da5cdc27a0f32f1e4dd173ea07e005b68107` |
| v1-nav | v1-evade + route to zone around buildings | 2.02 (assumed this commit) | 2.896 (96, 0.430) on the fixed sim; predicted -0.09 vs v1-evade, real -0.08 | `142bd263e319a2e5f5b82c79ae855d83766f121c` |
| v1-loot | v1-evade + loot by value/need/danger | 2.17 | bug-check only | `8d50f785cc4d31910713a557c7d5ea17355e70d9` |
| v1-lootheal | v1-loot + heal on purpose | 2.25 | bug-check only | `7e4fff1a6fa3a501e072c7b46e8337dad0fac694` |
| v1-early | v1-lootheal + grab a real weapon before the first fight | 2.35 | bug-check only (sim 2.396 vs v1-lootheal 2.010) | `8fb868cca27f7369e7ccf3ba1d3acde9cb25067b` |
| v1-cover | v1-early + move behind cover at spawn | 2.06 | sim paired vs v1-early +0.281 (96, SE 0.395); real -0.29 | `f1de99cf237319d4c4645b0c0847bccae67ec96f` |
| v1-crates | v1-early + one quiet opener crate attempt | 2.10 | sim paired vs v1-early +0.385 (96, SE 0.337); real -0.25 | `4ceec7d87d972588041a26d33e785edc8392837b` |

Known simulator numbers, all over 48 seeds starting at seed 1, with the older, uncalibrated
house-bot knobs: starter 2.396 (SE 0.486); v1 2.583 (SE 0.521); v2 all-on 1.438 (SE 0.289).
The order of the bots matches the real scorer, but the level is too high (the simulator's house
bots are too easy).

\* The v2 all-on simulator run predates the `react_unseen` patch, so it is not exactly bot E.
