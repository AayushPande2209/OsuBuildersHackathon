# Mech Royale offline simulator

This is a deterministic **approximation**, useful for comparing bot revisions and inspecting deaths. It is not the official scorer. The bundled `kit/` includes the real arena, recorded stream, schema, wrapper, and example bot. No network is needed. Python 3.10+ standard library suffices.

## Use

From the repository root:

```sh
python3 sim/run.py --bot 'python3 -u ../bot.py' --matches 48 --seed 1 --jobs 4 --slot random
python3 sim/report.py sim/out
python3 sim/viewer.py sim/out/match_0.jsonl
python3 sim/calibrate.py --matches 48 --seed 1 --jobs 4
python3 -m unittest discover -s sim/tests -v
```

`--bot` is executed with `sim/` as its working directory. `--map-dir` accepts a map path relative to your calling directory; it is converted to an absolute path for the bot's `hello`. The default is `sim/kit/arena`. `--slot` can be `random` or a fixed id 0–15. `--lockstep-relaxed` waits up to 10 seconds for each action, useful on a heavily loaded machine. Without it, actions arriving after 50 ms are dropped. Every match gets `seed + match_index`, independent of job scheduling. Replays are in `sim/out/`. The `.dockerignore` excludes all of `sim/` from the submission image.

A compact replay records the player's position, HP, aim, action, visible enemies, projectiles, damage events, and zone every decision. The HTML viewer draws the real map footprints plus those observations. It cannot show enemies hidden from the player's sensors.

## Calibration

`calibrate.py` runs both the kit example bot and the repository bot on identical seeds, prints both means and the current house difficulty knobs. Compare the printed results with the supplied real means (example ~1.15, current ~1.85). For 48 paired seeds starting at 1 with `--lockstep-relaxed`, the bundled example scored **2.396 ± 0.486 SE** and the current root bot scored **2.583 ± 0.521 SE** (November 20, 2026). Both exceed the supplied real means, so this simulator is **not calibrated**. Reducing house `aim_noise_deg` or `reaction_s` increases combat pressure; increasing `move_quality` helps house bots survive zone travel. Re-run the full calibration after changing any knob. Those real means are themselves samples; agreement is not proof of rule fidelity. The house squad fights only the player and NPCs. At match start one squad member hunts the player; more join over time, and all hunt after the configured ramp. House decisions use their own vision, with shared sightings and a decaying last-known player position. Tune all difficulty values in one block at the top of `house.py`.

## Known deviations and guesses

- The official server implementation was unavailable. The real config comes from the recorded `hello`, and every generated external protocol message is checked against the bundled schema. All 302 recorded messages validate with the local validator. The validator supports the subset of draft-07 keywords used in this schema, not arbitrary schemas.
- House behavior is invented. The real practice bots may fight each other; this squad does not. House bots share sightings, use simplified looting and movement, and have no simulated communication delay. This changes placement distribution and calibration.
- Projectile muzzle velocity does **not** inherit shooter velocity. The rulebook does not specify it. Spread is Gaussian per shot. Hits use a radial approximation to the target cylinder, so grazing vertical shots can differ from the server.
- Prism footprints, holes, base/top, terrain grid and bilinear terrain heights are real. Wall collision slides by trying the full move, then x and y components; step and slope checks are approximations. Roof edge overhang, canopy density, bridge eaves, and exact cylinder sweep are not modeled. Trees do not currently block vision, although the rulebook says dense crowns and trunks can.
- Vision follows near range, yaw field of view, prism/terrain line of sight, and memory timeout. Cached memory keeps current positions as specified. Sight line is tested to one point above the target rather than center **or** top. Sound timing and occlusion are approximations; sounds use the listed ranges and bearing noise but are retained for 0.3 seconds.
- NPCs chase and return home but do not wander while idle. They choose nearby targets rather than tracking who last attacked. Crate rooftops and loot rooftops are sampled from map prisms. Spawn packing uses rejection sampling and fails if 16 legal points cannot be found.
- Gun cooldown/reload, mortar gravity/splash, laser hold/release/cook-off, lightning cone/chain/short, HP/energy regen, cube scaling, offers, drops, zone interpolation, and same-tick death ties are modeled. Several exact edge cases differ: mortar direct-hit detection and blast cover, laser piercing upgrades, target surface collision, simultaneous interaction ordering, and late bot output handling are simplified. Cooldowns are quantized to 0.05-second simulation ticks.
- `--lockstep-relaxed` deliberately deviates from the 50 ms action deadline. The default runner enforces it with wall time. A crashed bot idles; a late bot coasts for 1 second then idles.
- After the player dies, a match stops immediately because placement and kills are fixed. This saves CPU and does not change the player's score. A living player is simulated to victory or 480 seconds.

Performance is seed dependent. The two-match smoke test uses two seeds that die early and measures under 60 seconds; long-lived 480-second matches can exceed the 30-second CPU target. The engine includes a prism spatial hash and edge precomputation, but the full target is not met on this machine.

The tests cover core math and protocol shape, but they do not establish equivalence to the official game. Use differences between repeated local versions as a signal, then check promising versions in the official scorer.
