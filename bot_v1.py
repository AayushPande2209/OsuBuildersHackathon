"""Frozen measured v1 strategy; selected when v2 experiments underperform."""
"""Mech Royale bot v1: survival-first. Zone-aware, wall-aware steering, lead-aimed gun, laser/lightning/mortar use."""
import json
import math
import random
import mechfight as mf

TAU = math.tau
PICK_PRIORITY = ["armor", "plating", "nanites", "gun_damage", "gun_rate", "laser_damage", "laser_charge",
                 "servos", "gun_mag", "lightning_efficiency", "lightning_chain", "gyros", "reactor",
                 "capacitor", "gun_velocity", "sensors", "mortar_reload", "mortar_splash", "jets",
                 "lightning_range", "laser_pierce", "mortar_velocity"]
WEAPON_RANK = {"laser": 3, "lightning": 2, "mortar": 1}


def wrap(a):
    return (a + math.pi) % TAU - math.pi


def seg_hit(px, py, dx, dy, ax, ay, bx, by):
    """Distance t along ray (px,py)+t*(dx,dy) (|d|=1) to segment ab, or None."""
    ex, ey = bx - ax, by - ay
    den = dx * ey - dy * ex
    if abs(den) < 1e-9:
        return None
    wx, wy = ax - px, ay - py
    t = (wx * ey - wy * ex) / den
    u = (wx * dy - wy * dx) / den
    if t >= 0 and 0 <= u <= 1:
        return t
    return None



# ---------------------------------------------------------------- roofs
ROOF_MIN_H = 6.0       # building must stand at least this tall (else it is no refuge)
ROOF_MAX_H = 40.0      # 100 energy climbs ~60 m; keep a margin
ROOF_CLEAR = 4.0       # safe spot at least this far from every roof edge
ROOF_SEARCH_M = 70.0   # only consider roofs whose safe spot is this close
ROOF_COOLDOWN_S = 10.0


def _pt_seg(px, py, ax, ay, bx, by):
    ex, ey = bx - ax, by - ay
    L = ex * ex + ey * ey
    u = 0.0 if L < 1e-9 else max(0.0, min(1.0, ((px - ax) * ex + (py - ay) * ey) / L))
    qx, qy = ax + ex * u, ay + ey * u
    return math.hypot(px - qx, py - qy), qx, qy


def _in_ring(ring, x, y):
    hit = False
    n = len(ring)
    for a in range(0, n, 2):
        b = (a + 2) % n
        ay, by = ring[a + 1], ring[b + 1]
        if (ay > y) != (by > y) and x < (ring[b] - ring[a]) * (y - ay) / (by - ay) + ring[a]:
            hit = not hit
    return hit


def build_roofs(path):
    """Climbable roofs: (sx, sy, top, base, edges) with a safe spot (sx, sy) >= ROOF_CLEAR from edges."""
    roofs = []
    w = json.load(open(path + "/v2/world.json"))
    for p in w["prisms"]:
        if p.get("kind") != "building":
            continue
        h = p["top"] - p["base"]
        if not (ROOF_MIN_H <= h <= ROOF_MAX_H):
            continue
        ring = p["ring"]
        holes = p.get("holes") or []
        xs, ys = ring[0::2], ring[1::2]
        if max(xs) - min(xs) < 2 * ROOF_CLEAR + 2 or max(ys) - min(ys) < 2 * ROOF_CLEAR + 2:
            continue
        edges = []
        for poly in [ring] + list(holes):
            n = len(poly) // 2
            for i in range(n):
                j = (i + 1) % n
                edges.append((poly[2 * i], poly[2 * i + 1], poly[2 * j], poly[2 * j + 1]))
        step = max(3.0, max(max(xs) - min(xs), max(ys) - min(ys)) / 16.0)
        best = None
        yy = min(ys) + step / 2
        while yy < max(ys):
            xx = min(xs) + step / 2
            while xx < max(xs):
                if _in_ring(ring, xx, yy) and not any(_in_ring(hh, xx, yy) for hh in holes):
                    c = min(_pt_seg(xx, yy, *e)[0] for e in edges)
                    if best is None or c > best[0]:
                        best = (c, xx, yy)
                xx += step
            yy += step
        if best and best[0] >= ROOF_CLEAR:
            roofs.append((best[1], best[2], p["top"], p["base"], edges))
    return roofs


class World:
    def __init__(self, path):
        self.pr = []  # (minx,miny,maxx,maxy,base,top,edges)
        try:
            w = json.load(open(path + "/v2/world.json"))
            for p in w["prisms"]:
                edges = []
                for ring in [p["ring"]] + list(p.get("holes") or []):
                    n = len(ring) // 2
                    for i in range(n):
                        j = (i + 1) % n
                        edges.append((ring[2 * i], ring[2 * i + 1], ring[2 * j], ring[2 * j + 1]))
                xs = p["ring"][0::2]
                ys = p["ring"][1::2]
                self.pr.append((min(xs), min(ys), max(xs), max(ys), p["base"], p["top"], edges))
        except Exception as e:  # map is optional
            mf.log("map load failed", e)
        self.near = []

    def refresh(self, x, y, z, r=90):
        self.near = [p for p in self.pr
                     if p[0] - r < x < p[2] + r and p[1] - r < y < p[3] + r and p[4] < z + 9 and p[5] > z + 1.5]

    def free(self, x, y, ang, maxd, lat=2.6):
        """Free distance along heading ang (checks centre + both sides)."""
        dx, dy = math.cos(ang), math.sin(ang)
        best = maxd
        for off in (0.0, lat, -lat):
            px, py = x - dy * off, y + dx * off
            for p in self.near:
                if p[0] - maxd > px or px > p[2] + maxd or p[1] - maxd > py or py > p[3] + maxd:
                    continue
                for e in p[6]:
                    t = seg_hit(px, py, dx, dy, *e)
                    if t is not None and t < best:
                        best = t
        return best

    def los(self, x, y, tx, ty, z):
        d = math.hypot(tx - x, ty - y)
        if d < 1:
            return True
        ang = math.atan2(ty - y, tx - x)
        dx, dy = math.cos(ang), math.sin(ang)
        for p in self.pr:
            if p[4] > z + 9 or p[5] < z + 3:
                continue
            if max(x, tx) < p[0] or min(x, tx) > p[2] or max(y, ty) < p[1] or min(y, ty) > p[3]:
                continue
            for e in p[6]:
                t = seg_hit(x, y, dx, dy, *e)
                if t is not None and t < d:
                    return False
        return True


class Bot:
    name = "survivor-v1"

    def __init__(self, hello):
        cfg = hello["config"]
        self.cfg = cfg
        self.rng = random.Random(hello.get("seed", 1))
        self.world = World(hello["map"]["dir"])
        try:
            self.roofs = build_roofs(hello["map"]["dir"])
        except Exception as e:  # roofs are optional
            mf.log("roof scan failed", type(e).__name__, str(e)[:80])
            self.roofs = []
        mf.log("roofs", len(self.roofs))
        self.roof = None        # (sx, sy, top, base, edges)
        self.roof_state = None  # None | "go" | "climb" | "on"
        self.roof_t0 = -99.0
        self.roof_edge = None
        self.roof_cool = -99.0
        self.strafe = 1
        self.strafe_until = 0
        self.last_dir = None
        self.stuck = 0
        self.escape_until = -1
        self.escape_dir = 0.0
        self.prev_pos = None
        self.scan = 0.0
        self.sound_bearing = None
        self.sound_t = -99
        self.laser_held = False
        self.dmg_t = -99.0
        self.dmg_bearing = None

    # ---------------------------------------------------------------- roof logic
    def roof_ok(self, r, zc, zr, nzc, nzr, heading_next, margin=20.0):
        if math.hypot(r[0] - zc[0], r[1] - zc[1]) > zr - margin:
            return False
        if heading_next and math.hypot(r[0] - nzc[0], r[1] - nzc[1]) > nzr - margin:
            return False
        return True

    def roof_logic(self, obs, me, t, x, y, z, mx, my, jump, boost, mode,
                   mechs, close, hp_frac, zc, zr, nzc, nzr, heading_next):
        st = self.roof_state
        if st is None:
            if t < self.roof_cool or t < 8 or not self.roofs or not mechs:
                return mx, my, jump, boost, mode
            near = [m for m in mechs if math.hypot(m["pos"][0] - x, m["pos"][1] - y) < 140]
            if not near:
                return mx, my, jump, boost, mode
            hurt = hp_frac < 0.75 or len(close) >= 2 or t - self.dmg_t < 3.0
            if not hurt:
                return mx, my, jump, boost, mode
            ex, ey = near[0]["pos"][0], near[0]["pos"][1]
            best = None
            for r in self.roofs:
                d = math.hypot(r[0] - x, r[1] - y)
                if d > ROOF_SEARCH_M or r[2] < z + 4.0:
                    continue
                need = 1.7 * (r[2] - z) + 12.0
                if need > me["energy"] or not self.roof_ok(r, zc, zr, nzc, nzr, heading_next):
                    continue
                score = d - 0.3 * math.hypot(r[0] - ex, r[1] - ey)
                if best is None or score < best[0]:
                    best = (score, r)
            if best is None:
                return mx, my, jump, boost, mode
            self.roof = best[1]
            self.roof_state = "go"
            self.roof_t0 = t
            dmin, qx, qy = min(_pt_seg(x, y, *e) for e in self.roof[4])
            self.roof_edge = (qx, qy)
            mf.log("roof go", f"t={t:.0f}", f"hp={me['hp']:.0f}", f"en={me['energy']:.0f}", f"top={self.roof[2]:.0f}", f"d={dmin:.0f}")
            st = "go"
        r = self.roof
        sx, sy, top = r[0], r[1], r[2]
        def abort(why, cool=ROOF_COOLDOWN_S):
            mf.log("roof abort", why, f"t={t:.0f}", f"hp={me['hp']:.0f}")
            self.roof_state = None
            self.roof_cool = t + cool
        if st == "go":
            if t - self.roof_t0 > 12.0 or (not me["in_zone"]):
                abort("go-timeout")
                return mx, my, jump, boost, mode
            qx, qy = self.roof_edge
            d = math.hypot(qx - x, qy - y)
            if d < 5.0:
                self.roof_state = "climb"
                self.roof_t0 = t
                st = "climb"
            else:
                a = math.atan2(qy - y, qx - x)
                return math.cos(a), math.sin(a), jump, me["energy"] > 1.7 * (top - z) + 25, "roof-go"
        if st == "climb":
            if t - self.roof_t0 > 7.0:
                abort("climb-timeout")
                return mx, my, jump, boost, mode
            if me["grounded"] and z > top - 1.0:
                self.roof_state = "on"
                self.roof_t0 = t
                mf.log("roof on", f"t={t:.0f}", f"hp={me['hp']:.0f}", f"top={top:.0f}")
                st = "on"
            else:
                a = math.atan2(sy - y, sx - x)
                rising = z < top + 1.5
                # press toward the roof while jetting; walls slide us along until our feet clear the edge
                return math.cos(a), math.sin(a), True, me["energy"] > 0 and rising, "roof-climb"
        if st == "on":
            if z < top - 2.5:
                abort("fell-off", 5.0)
                return mx, my, jump, boost, mode
            if (not me["in_zone"]) or not self.roof_ok(r, zc, zr, nzc, nzr, heading_next, margin=5.0):
                abort("zone", 30.0)
                return mx, my, jump, boost, mode
            d = math.hypot(sx - x, sy - y)
            if d > 2.5:
                a = math.atan2(sy - y, sx - x)
                return math.cos(a) * 0.7, math.sin(a) * 0.7, False, False, "roof"
            return 0.0, 0.0, False, False, "roof"
        return mx, my, jump, boost, mode

    # ---------------------------------------------------------------- helpers
    def zone_now(self, z, t):
        if t <= z["shrink_start"]:
            return z["center"], z["radius"]
        if t >= z["shrink_end"]:
            return z["next_center"], z["next_radius"]
        f = (t - z["shrink_start"]) / max(1e-6, z["shrink_end"] - z["shrink_start"])
        c = [z["center"][i] + (z["next_center"][i] - z["center"][i]) * f for i in (0, 1)]
        return c, z["radius"] + (z["next_radius"] - z["radius"]) * f

    def lead(self, src, tpos, tvel, speed):
        r = [tpos[i] - src[i] for i in range(3)]
        a = tvel[0] ** 2 + tvel[1] ** 2 + tvel[2] ** 2 - speed ** 2
        b = 2 * (r[0] * tvel[0] + r[1] * tvel[1] + r[2] * tvel[2])
        c = r[0] ** 2 + r[1] ** 2 + r[2] ** 2
        t = None
        if abs(a) < 1e-6:
            if abs(b) > 1e-6:
                t = -c / b
        else:
            disc = b * b - 4 * a * c
            if disc >= 0:
                s = math.sqrt(disc)
                ts = [x for x in ((-b - s) / (2 * a), (-b + s) / (2 * a)) if x > 0]
                if ts:
                    t = min(ts)
        if t is None or t <= 0 or t > 2:
            t = math.sqrt(c) / speed
        return [tpos[i] + tvel[i] * t for i in range(3)]

    def angles(self, src, dst):
        dx, dy, dz = dst[0] - src[0], dst[1] - src[1], dst[2] - src[2]
        return math.atan2(dy, dx), math.atan2(dz, math.hypot(dx, dy))

    def mortar_aim(self, src, tpos, tvel, speed, g):
        p = list(tpos)
        for _ in range(3):
            R = math.hypot(p[0] - src[0], p[1] - src[1])
            dz = p[2] - src[2]
            v2 = speed * speed
            disc = v2 * v2 - g * (g * R * R + 2 * dz * v2)
            if disc < 0:
                return None
            pitch = math.atan((v2 - math.sqrt(disc)) / (g * R)) if R > 1 else 0.7
            tof = R / (speed * math.cos(pitch))
            p = [tpos[0] + tvel[0] * tof, tpos[1] + tvel[1] * tof, tpos[2]]
        yaw = math.atan2(p[1] - src[1], p[0] - src[0])
        return yaw, pitch

    def steer(self, x, y, want):
        """Pick the heading closest to `want` with room ahead."""
        look = 22.0
        order = [0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7, 8]
        if self.last_dir is not None and self.last_dir < 0:
            order = [0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -7, 7, 8]
        bestk, bestfr = 0, -1.0
        for k in order:
            fr = self.world.free(x, y, want + k * 0.35, look)
            if fr >= look - 0.5:
                if k:
                    self.last_dir = k
                return want + k * 0.35
            if fr > bestfr:
                bestk, bestfr = k, fr
        return want + bestk * 0.35

    # ---------------------------------------------------------------- main
    def act(self, obs):
        me = obs["self"]
        x, y, z = me["pos"]
        t = obs["t"]
        tick = obs["tick"]
        act = {"tick": tick}
        stats = me["stats"]
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        self.world.refresh(x, y, z)
        scale = 1 + 0.05 * me["cubes"]
        muzzle_h = stats.get("muzzle_height", 7 * scale)

        # offer
        if obs["offer"]:
            ids = [c["id"] for c in obs["offer"]["choices"]]
            pick = min(range(len(ids)), key=lambda i: PICK_PRIORITY.index(ids[i]) if ids[i] in PICK_PRIORITY else 99)
            act["pick"] = pick

        for ev in obs.get("events", []):
            if ev.get("type") == "damaged" and ev.get("weapon") != "zone" and ev.get("bearing") is not None:
                self.dmg_t = t
                self.dmg_bearing = ev["bearing"]

        # stuck detection
        speed = math.hypot(me["vel"][0], me["vel"][1])

        # sounds
        for s in obs["sounds"]:
            if s["kind"] in ("gun", "mortar", "explosion", "laser", "lightning", "step", "boost", "npc_gun") and s["dist"] != "far":
                self.sound_bearing = s["bearing"]
                self.sound_t = t

        mechs = [m for m in obs["mechs"] if m["kind"] == "mech"]
        npcs = [m for m in obs["mechs"] if m["kind"] == "npc"]
        d2 = lambda p: math.hypot(p[0] - x, p[1] - y)
        mechs.sort(key=lambda m: d2(m["pos"]) - (60 if m.get("hp", 1400) < 400 else 0))
        close = [m for m in mechs if d2(m["pos"]) < 110]

        zc, zr = self.zone_now(obs["zone"], t)
        nzc, nzr = obs["zone"]["next_center"], obs["zone"]["next_radius"]
        dz_center = math.hypot(x - zc[0], y - zc[1])
        dn_center = math.hypot(x - nzc[0], y - nzc[1])

        # ---------------- weapons
        wk = [w["kind"] if w else None for w in me["weapons"]]

        def slot(kind):
            return wk.index(kind) if kind in wk else None

        # pickups
        reach = self.cfg["loot"]["pickup_radius"] - 0.6
        near_pick = [p for p in obs["pickups"] if math.hypot(p["pos"][0] - x, p["pos"][1] - y) < reach and abs(p["pos"][2] - z) < 3.5]
        for p in sorted(near_pick, key=lambda p: -WEAPON_RANK.get(p["kind"], 0)):
            if p["kind"] == "gun" or p["kind"] in wk:
                continue
            if wk[1] is None:
                act["take"] = p["id"]
                break
            if wk[0] is None:
                act["take"] = p["id"]
                break
            have = WEAPON_RANK.get(wk[1], 0)
            if wk[1] and WEAPON_RANK.get(p["kind"], 0) > have:
                act["take"] = p["id"]
                act["drop"] = 1
                break

        # ---------------- target & fire
        target = None
        fire = [False, False]
        aim = None
        if mechs:
            target = mechs[0]
        if target is None and npcs and hp_frac > 0.6:
            n0 = min(npcs, key=lambda m: d2(m["pos"]))
            if d2(n0["pos"]) < 70:
                target = n0
        tgt_d = None
        if target is not None:
            tp = target["pos"]
            ts = 1 + 0.05 * target.get("cubes", 0) if target["kind"] == "mech" else 0.4
            tcenter = [tp[0], tp[1], tp[2] + 4.5 * ts]
            tgt_d = d2(tp)
            src = [x, y, z + muzzle_h]
            visible_los = self.world.los(x, y, tp[0], tp[1], z)
            g = slot("gun")
            lz = slot("laser")
            lt = slot("lightning")
            mo = slot("mortar")
            gun_speed = me["weapons"][g]["stats"]["speed"] if g is not None else 252
            lead_pt = self.lead(src, tcenter, target["vel"], gun_speed)
            yaw_l, pit_l = self.angles(src, lead_pt)
            yaw_d, pit_d = self.angles(src, tcenter)
            aim = [yaw_l, pit_l]
            tol = max(0.025, min(0.14, 2.2 / max(5.0, tgt_d)))
            cur_yaw, cur_pit = me["aim"]
            err_l = abs(wrap(yaw_l - cur_yaw))
            charging_laser = lz is not None and (me["weapons"][lz].get("charge", 0) > 0)

            if lz is not None and (charging_laser or (tgt_d < 230 and visible_los)):
                aim = [yaw_d, pit_d]  # hitscan: no lead
                err = abs(wrap(yaw_d - cur_yaw))
                w = me["weapons"][lz]
                if w["cooldown"] <= 0.05 or charging_laser:
                    ch = w.get("charge", 0)
                    full = self.cfg["weapons"]["laser"]["charge"] * 0.92
                    if ch >= full and err < tol * 1.3:
                        fire[lz] = False  # release
                    elif ch > 0.3 and err > 0.25:
                        fire[lz] = False
                    else:
                        fire[lz] = True
            if g is not None and not (lz is not None and fire[lz]):
                w = me["weapons"][g]
                if tgt_d < 215 and visible_los and err_l < tol and w.get("ammo", 1) > 0 and w["reload"] <= 0:
                    fire[g] = True
            if lt is not None and tgt_d < 42 and me["energy"] > 12 and visible_los:
                fire[lt] = True
                if tgt_d < 38 and lz is None:
                    aim = [yaw_d, pit_d]
            if mo is not None and 25 < tgt_d < 200 and (not visible_los or tgt_d > 90 or g is None):
                ma = self.mortar_aim([x, y, z + 9.5 * scale], tcenter, target["vel"],
                                     me["weapons"][mo]["stats"].get("speed", 72), self.cfg["weapons"]["mortar"]["gravity"])
                if ma and not (g is not None and fire[g]) and not (lz is not None and fire[lz]):
                    aim = list(ma)
                    if abs(wrap(ma[0] - cur_yaw)) < 0.08 and me["weapons"][mo]["cooldown"] <= 0.05:
                        fire[mo] = True
            if aim is not None:
                aim[1] = max(self.cfg["mech"]["min_pitch"], min(self.cfg["mech"]["max_pitch"], aim[1]))
        # reload when calm
        if not close and g_ammo_low(me):
            act["reload"] = True

        # ---------------- movement
        mx, my = 0.0, 0.0
        boost = False
        mode = "idle"

        def toward(px, py, w=1.0):
            a = math.atan2(py - y, px - x)
            return math.cos(a) * w, math.sin(a) * w

        zone_margin = 18.0
        edge_pressure = max(0.0, (dz_center - (zr - 40)) / 40.0)  # grows near/outside edge
        outside = (not me["in_zone"]) or dz_center > zr - 6
        # next-circle readiness: start heading to it once the phase is about to shrink
        heading_next = t > obs["zone"]["shrink_start"] - 25 or dn_center > nzr * 0.9

        if outside:
            mode = "zone"
            tx_, ty_ = toward(zc[0], zc[1])
            mx, my = tx_, ty_
            boost = me["energy"] > 15
        elif target is not None and tgt_d is not None and tgt_d < 140:
            mode = "fight"
            ex, ey = target["pos"][0] - x, target["pos"][1] - y
            ed = math.hypot(ex, ey) + 1e-6
            rx, ry = ex / ed, ey / ed
            n_threat = len([m for m in close if d2(m["pos"]) < 100])
            flee = (hp_frac < 0.33 and ed > 12) or n_threat >= 3
            if t > self.strafe_until:
                self.strafe = -self.strafe if self.rng.random() < 0.6 else self.strafe
                self.strafe_until = t + self.rng.uniform(0.7, 1.8)
            px_, py_ = -ry * self.strafe, rx * self.strafe
            desired = 70.0
            if slot("lightning") is not None and slot("laser") is None:
                desired = 28.0
            radial = max(-1.0, min(1.0, (ed - desired) / 40.0))
            if flee:
                mode = "flee"
                mx, my = -rx * 1.0 + px_ * 0.4, -ry * 1.0 + py_ * 0.4
                zx, zy = toward(zc[0], zc[1], 0.5)
                mx += zx
                my += zy
                boost = me["energy"] > 20 and ed < 70
            else:
                mx, my = px_ + rx * radial * 0.8, py_ + ry * radial * 0.8
                zx, zy = toward(zc[0], zc[1], edge_pressure * 1.5)
                mx += zx
                my += zy
        elif self.dmg_bearing is not None and t - self.dmg_t < 3.0 and not (target is not None and tgt_d is not None and tgt_d < 140):
            # Shot by something we cannot see: do not stand still. Run away from the shot's
            # origin with a sideways wobble, biased toward the zone.
            mode = "evade-unseen"
            ax, ay = -math.cos(self.dmg_bearing), -math.sin(self.dmg_bearing)
            if t > self.strafe_until:
                self.strafe = -self.strafe
                self.strafe_until = t + 1.0
            mx, my = ax - ay * 0.5 * self.strafe, ay + ax * 0.5 * self.strafe
            zx, zy = toward(zc[0], zc[1], 0.35)
            mx += zx
            my += zy
            boost = me["energy"] > 40 and hp_frac < 0.6
        else:
            # not fighting: loot, drops, zone positioning
            goal = None
            pk = [p for p in obs["pickups"] if p["kind"] != "gun" and p["kind"] not in wk
                  and math.hypot(p["pos"][0] - zc[0], p["pos"][1] - zc[1]) < zr - 15]
            if pk and (wk[1] is None or wk[0] is None) and hp_frac > 0.35:
                p = min(pk, key=lambda p: d2(p["pos"]))
                if d2(p["pos"]) < 90:
                    goal = p["pos"]
                    mode = "loot"
            if goal is None:
                cu = [c for c in obs["cubes"] if d2(c["pos"]) < 45 and math.hypot(c["pos"][0] - zc[0], c["pos"][1] - zc[1]) < zr - 12]
                if cu and hp_frac > 0.4:
                    goal = min(cu, key=lambda c: d2(c["pos"]))["pos"]
                    mode = "cube"
            if goal is None:
                for dr in obs["drops"]:
                    dd = d2(dr["pos"])
                    if dd < 140 and dr["lands_in"] * 11 < dd + 40 and dr["holder"] in (None, me["id"]):
                        if math.hypot(dr["pos"][0] - zc[0], dr["pos"][1] - zc[1]) < zr - 10:
                            goal = dr["pos"]
                            mode = "drop"
                            if dd < dr["radius"] * 0.5 and dr["lands_in"] <= 0:
                                goal = None
                                mode = "hold-drop"
                                mx = my = 0.0
                            break
            if goal is None and mode != "hold-drop":
                # position inside the circle we're heading to
                cx_, cy_ = (nzc if heading_next else zc)
                rr = (nzr if heading_next else zr) * 0.45
                d = math.hypot(x - cx_, y - cy_)
                if d > rr:
                    goal = [cx_, cy_]
                    mode = "zone-move"
            if goal is not None:
                mx, my = toward(goal[0], goal[1])
                dgoal = math.hypot(goal[0] - x, goal[1] - y)
                if dgoal < 3.5 and mode in ("loot", "cube"):
                    mx, my = mx * 0.2, my * 0.2
            elif mode == "idle":
                mx = my = 0.0

        # dodge incoming enemy projectiles
        for pr in obs["projectiles"]:
            px, py = pr["pos"][0] - x, pr["pos"][1] - y
            vx, vy = pr["vel"][0], pr["vel"][1]
            vs = math.hypot(vx, vy) + 1e-6
            along = -(px * vx + py * vy) / vs
            if 0 < along < 30 + vs * 0.25 and math.hypot(px, py) < 90:
                cross = (px * vy - py * vx) / vs
                if abs(cross) < 5:
                    s = 1 if cross <= 0 else -1
                    mx += (-vy / vs) * s * 1.4
                    my += (vx / vs) * s * 1.4
                    if mode == "idle":
                        mode = "dodge"

        # stuck / escape
        moving_cmd = math.hypot(mx, my)
        if moving_cmd > 0.4 and speed < 1.5 and me["grounded"]:
            self.stuck += 1
        else:
            self.stuck = max(0, self.stuck - 1)
        jump = False
        if self.stuck >= 6 and t > self.escape_until:
            self.escape_until = t + 1.2
            self.escape_dir = self.rng.uniform(-math.pi, math.pi)
            self.stuck = 0
        if t < self.escape_until:
            mx, my = math.cos(self.escape_dir), math.sin(self.escape_dir)
            jump = True
            boost = me["energy"] > 30
            mode = "escape"
        elif moving_cmd > 0.05:
            ang = self.steer(x, y, math.atan2(my, mx))
            n = min(1.0, moving_cmd)
            mx, my = math.cos(ang) * n, math.sin(ang) * n

        # laser charging halves speed anyway; boost only when energy ok
        if boost and me["energy"] < 8:
            boost = False

        # ---------------- roofs: climb out of reach when the fight turns against us
        try:
            mx, my, jump, boost, mode = self.roof_logic(obs, me, t, x, y, z, mx, my, jump, boost, mode,
                                                         mechs, close, hp_frac, zc, zr, nzc, nzr, heading_next)
        except Exception as e:
            mf.log("roof error", type(e).__name__, str(e)[:80])
            self.roof_state = None

        # ---------------- aim when no target: scan toward sounds, else slow sweep
        if aim is None:
            if self.sound_bearing is not None and t - self.sound_t < 3:
                aim = [self.sound_bearing, 0.0]
            elif moving_cmd > 0.3 and mode in ("zone", "zone-move", "loot", "cube", "drop", "escape"):
                aim = [math.atan2(my, mx), 0.0]
            else:
                self.scan += 0.5
                aim = [me["aim"][0] + 0.9, 0.0]

        act.update(move=[round(mx, 3), round(my, 3)], boost=boost, jump=jump,
                   aim=[round(wrap(aim[0]), 4), round(aim[1], 4)], fire=fire)
        mf.draw.label(f"{mode} hp{me['hp']:.0f}")
        return act


def g_ammo_low(me):
    w = me["weapons"][0]
    return bool(w and w["kind"] == "gun" and w.get("ammo", 99) < 6 and w.get("reload", 0) <= 0)


class SafeBot(Bot):
    """Keep the v1 decisions while guaranteeing a protocol answer on errors."""

    def act(self, obs):
        try:
            return super().act(obs)
        except Exception as exc:
            t = obs.get("t", 0)
            if t - getattr(self, "_last_error_t", -99) >= 5:
                mf.log("v1 fallback", type(exc).__name__, str(exc)[:100])
                self._last_error_t = t
            action = {"tick": obs.get("tick", 0), "move": [0, 0], "fire": [False, False]}
            if obs.get("offer"):
                action["pick"] = 0
            return action

