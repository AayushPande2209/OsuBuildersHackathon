# Mech Royale v2 notes

`bot.py` retains the `mechfight.py` wrapper and uses only the Python standard library. Every v2 behavior has a Boolean switch near the top of `bot.py`; numeric tuning values are in the same `CONFIG` dictionary. The Docker context includes only `Dockerfile`, `bot.py`, `bot_v1.py`, and `mechfight.py`.

`legacy_strategy=True` selects the measured v1 behavior by default. Set it to `False` to activate the v2 switches below. The v2 route was disabled because it performed worse on paired local simulator seeds; this is a deliberately conservative default pending real scorer results.

## Modules and knobs

| Module | Behavior | Main knobs |
| --- | --- | --- |
| Map and hideouts (§7–9) | Parse prisms at hello time; cache low-exposure ground corners and roofs with interior clearance; periodically choose a point inside the announced circle. | `hideouts`, `roofs`, `roof_min_height`, `roof_max_rise`, `roof_edge_margin`, `hide_reselect_s`, `hide_zone_margin`, `hide_distance_weight`, `hide_exposure_weight`, `hide_roof_bonus`, `hide_center_weight` |
| Climb (§7) | Walk to an outside wall point, jet vertically above the roof, cross inward, and abandon failed attempts. | `climb_energy_margin`, `climb_timeout_s`, `climb_stall_s` |
| Stealth (§8) | Walk below the step sound threshold; hold aim still when quiet; avoid firing at distant mechs and ignore drones by default. | `stealth`, `quiet_move`, `selective_fire`, `engage_range`, `fire_after_damage_s`, `npc_farm` |
| Defence (§7–8) | Face visible or recent attackers, move sideways, flee at low HP or against several opponents, dodge direct bullets, mortar impacts, and laser charging lines. | `flee_hp_fraction`, `flee_enemy_count`, `flee_boost_energy`, `evasion`, `projectile_dodge_radius`, `mortar_dodge_radius`, `laser_dodge_range` |
| Loot and drops (§7, §10) | Take nearby weapons and cubes when safe; consider a close, uncontested drop at low HP. | `safe_loot`, `initial_loot_s`, `loot_radius`, `cube_radius`, `enemy_safe_range`, `drops`, `drop_interest_radius` |
| Zone and endgame (§9) | Reposition toward the next circle; move faster if a quiet walk cannot beat the closing zone; wait when already safe with few mechs left. | `endgame`, `hide_next_lead_s`, `roof_leave_s`, `zone_travel_buffer_s`, `zone_urgent_energy` |
| Upgrades and reliability (§6, §10) | Pick defensive upgrades first, then upgrades for equipped weapons; always return a safe action after an exception. Recover from stalled walking. | `upgrades`, `stuck_recovery`, `stuck_ticks`, `log_every_s` |

The v1 combat aiming and weapon logic remains in place. Mortar use is opportunistic and may expose the bot. `npc_farm` is disabled by default because a gunshot is audible at 320 m. Roof access by house bots has not been verified in the real game.

## Measurement

The simulator is an approximation being developed in a separate checkout. Its house bots and movement model are not yet calibrated to the real scorer, so placement numbers below cannot be treated as real leaderboard estimates. The paired run used a frozen copy of the same simulator code and map for both bots.

| Bot / change | Simulator version | Seeds | Matches | Mean `(16 - place)` | Decision |
| --- | --- | --- | ---: | ---: | --- |
| v1 baseline | frozen snapshot | 1–2 | 2 | 8.5 | Reference |
| v2, all main switches on | frozen snapshot | 1–2 | 2 | 1.5 | Disabled by `legacy_strategy=True` |
| v1 baseline | final simulator snapshot | 1–48 | 48 | 2.583 (SE 0.521) | Default strategy |
| v2, all main switches on | final simulator snapshot | 1–48 | 48 | 1.438 (SE 0.289) | Disabled by `legacy_strategy=True` |

The starter benchmark on the final simulator snapshot scored 2.396 over 48 matches, versus the supplied real starter result of about 1.15. The simulator's v1 score is also above its supplied real 1.85. The simulator is therefore not calibrated to predict leaderboard placement. The final simulator snapshot used engine SHA-1 `159df63e8586c2648e118e305eb69686075d1493` and house SHA-1 `08ce04c66c1ccefbb321d2d4af8828e2e9962433`.

The kit `check.py` passed on every v2 commit. With v2 active, the check answered all 300 observations on time; local p99 was 1.4 ms and hello initialization 3.9 s. With the legacy default, p99 was 2.0 ms and hello initialization 0.1 s. These timings are from the local machine, not a 1 CPU Docker match. Docker CLI is present, but its daemon was unavailable, so the image build was not run.

## Next real-scorer A/B tests

1. Set `legacy_strategy=False`, then compare `roofs=True` and `roofs=False` on the same submitted seeds if the platform allows fixed seeds. Roof routes are the highest-risk new behavior.
2. Compare `selective_fire=True` and `False`; a squad that already knows the bot's location may punish withholding shots.
3. Compare `quiet_move=0.36` with a faster zone-safe value, while checking step sound exposure and time spent outside the next circle.
4. Check real match logs for `roof-abort`, `zone-urgent`, and repeated `escape` modes. Increase the approach margin or disable roofs if a map position traps the mech.

No 3.0+ real score is claimed. The real scorer and house bot roof behavior are unavailable locally.
