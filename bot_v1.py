"""Frozen measured v1 strategy; selected when v2 experiments underperform."""
"""Mech Royale bot v1: survival-first. Zone-aware, wall-aware steering, lead-aimed gun, laser/lightning/mortar use."""
import array
import heapq
import json
import math
import random
import sys
import time
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


class Nav:
    """Walkable 4 m grid built from the map, plus a walking-distance field to the zone centre.

    Buildings that would stop a mech are walls; ground slopes too steep to walk are walls;
    cells next to walls cost extra so routes keep clear of them. The distance field is
    computed with Dijkstra in small time slices so no decision goes over budget.
    """
    CELL = 4.0
    HEAD = 9.0
    STEP = 1.2
    SLICE_S = 0.010
    NEAR_WALL_COST = 2.5
    JET_MAX = 30.0   # walls up to this height above the ground can be jetted over (100 energy climbs ~60 m)

    def __init__(self, path):
        t0 = time.perf_counter()
        w = json.load(open(path + "/v2/world.json"))
        tm = w["terrain"]
        tnx, tny = tm["nx"], tm["ny"]
        hts = array.array("h")
        with open(path + "/v2/" + tm.get("file", "terrain.i16"), "rb") as f:
            hts.frombytes(f.read())
        if sys.byteorder == "big":
            hts.byteswap()
        sc = tm.get("scale", 0.01)
        b = w["bounds"]
        c = self.CELL
        self.x0, self.y0 = b["minX"], b["minY"]
        self.nx = int((b["maxX"] - b["minX"]) / c) + 1
        self.ny = int((b["maxY"] - b["minY"]) / c) + 1
        nx, ny = self.nx, self.ny
        n = nx * ny
        ground = array.array("f", bytes(4 * n))
        for j in range(ny):
            ty = int(round((self.y0 + (j + 0.5) * c - tm["minY"]) / tm["step"]))
            ty = min(tny - 1, max(0, ty)) * tnx
            for i in range(nx):
                tx = int(round((self.x0 + (i + 0.5) * c - tm["minX"]) / tm["step"]))
                ground[j * nx + i] = hts[ty + min(tnx - 1, max(0, tx))] * sc
        self.ground = ground
        blocked = bytearray(n)
        wall_h = array.array("f", bytes(4 * n))
        for p in w["prisms"]:
            ring = p["ring"]
            holes = p.get("holes") or []
            xs, ys = ring[0::2], ring[1::2]
            i0 = max(0, int((min(xs) - self.x0) / c))
            i1 = min(nx - 1, int((max(xs) - self.x0) / c))
            j0 = max(0, int((min(ys) - self.y0) / c))
            j1 = min(ny - 1, int((max(ys) - self.y0) / c))
            for j in range(j0, j1 + 1):
                cy = self.y0 + (j + 0.5) * c
                for i in range(i0, i1 + 1):
                    k = j * nx + i
                    cx = self.x0 + (i + 0.5) * c
                    if not _inside(ring, cx, cy) or any(_inside(h, cx, cy) for h in holes):
                        continue
                    g = ground[k]
                    if p["base"] < g + self.HEAD and p["top"] > g + self.STEP:
                        blocked[k] = 1
                        wall_h[k] = max(wall_h[k], p["top"] - g)
        jet = bytearray(n)
        for k in range(n):
            if blocked[k] and wall_h[k] <= self.JET_MAX:
                blocked[k] = 0
                jet[k] = 1
        cost = array.array("f", [1.0]) * n
        for j in range(ny):
            for i in range(nx):
                k = j * nx + i
                if blocked[k]:
                    continue
                for dj in (-1, 0, 1):
                    for di in (-1, 0, 1):
                        ii, jj = i + di, j + dj
                        if 0 <= ii < nx and 0 <= jj < ny and blocked[jj * nx + ii]:
                            cost[k] = self.NEAR_WALL_COST
        top_abs = array.array("f", bytes(4 * n))
        for k in range(n):
            if jet[k]:
                cost[k] = 3.0 + wall_h[k] / 3.0  # taller walls cost more to cross
                top_abs[k] = ground[k] + wall_h[k]
        self.top_abs = top_abs
        self.blocked = blocked
        self.jet = jet
        self.cost = cost
        self.climb = math.tan(math.radians(48)) * c  # max rise between neighbouring cells
        self.goal = None
        self.dist = None
        self.heap = None
        self.done = False
        mf.log("nav grid", f"{nx}x{ny}", f"blocked={sum(blocked)}", f"{time.perf_counter() - t0:.2f}s")

    def cell(self, x, y):
        i = int((x - self.x0) / self.CELL)
        j = int((y - self.y0) / self.CELL)
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return i, j
        return None

    def center(self, i, j):
        return self.x0 + (i + 0.5) * self.CELL, self.y0 + (j + 0.5) * self.CELL

    def start(self, gx, gy, seed_r=30.0):
        """Begin a new distance field toward (gx, gy); free cells within seed_r are sources."""
        nx, ny = self.nx, self.ny
        self.goal = (gx, gy)
        self.dist = array.array("d", [1e9]) * (nx * ny)
        self.heap = []
        r = int(seed_r / self.CELL) + 1
        gc = self.cell(gx, gy)
        if gc is None:
            gc = (min(nx - 1, max(0, int((gx - self.x0) / self.CELL))), min(ny - 1, max(0, int((gy - self.y0) / self.CELL))))
        for rr in (r, 3 * r, 8 * r):
            for j in range(max(0, gc[1] - rr), min(ny, gc[1] + rr + 1)):
                for i in range(max(0, gc[0] - rr), min(nx, gc[0] + rr + 1)):
                    k = j * nx + i
                    if not self.blocked[k]:
                        cx, cy = self.center(i, j)
                        d = math.hypot(cx - gx, cy - gy)
                        if d <= rr * self.CELL:
                            self.dist[k] = d
                            self.heap.append((d, k))
            if self.heap:
                break
        heapq.heapify(self.heap)
        self.done = not self.heap

    def step(self):
        if self.done or self.heap is None:
            return
        t_end = time.perf_counter() + self.SLICE_S
        heap, dist, blocked, cost, ground = self.heap, self.dist, self.blocked, self.cost, self.ground
        nx, ny, climb, c = self.nx, self.ny, self.climb, self.CELL
        diag = c * 1.4142
        n_ops = 0
        while heap:
            d, k = heapq.heappop(heap)
            if d > dist[k]:
                continue
            j, i = divmod(k, nx)
            gk = ground[k]
            for di, dj, L in ((1, 0, c), (-1, 0, c), (0, 1, c), (0, -1, c),
                              (1, 1, diag), (1, -1, diag), (-1, 1, diag), (-1, -1, diag)):
                ii, jj = i + di, j + dj
                if not (0 <= ii < nx and 0 <= jj < ny):
                    continue
                m = jj * nx + ii
                if blocked[m]:
                    continue
                if di and dj and (blocked[j * nx + ii] or blocked[jj * nx + i]):
                    continue  # no corner cutting
                if gk - ground[m] > climb:
                    continue  # walking m -> k would climb a slope that is too steep
                nd = d + L * cost[m]
                if nd < dist[m]:
                    dist[m] = nd
                    heapq.heappush(heap, (nd, m))
            n_ops += 1
            if n_ops & 255 == 0 and time.perf_counter() > t_end:
                return
        self.done = True

    def waypoint(self, x, y, z=-1e9, look=5):
        """(x, y, climb) about `look` cells ahead on the shortest route to the goal, or None.
        climb > 0: the next cells are a wall top that many metres above the bot's feet."""
        if not self.done or self.dist is None:
            return None
        cc = self.cell(x, y)
        if cc is None:
            return None
        nx, ny, dist = self.nx, self.ny, self.dist
        i, j = cc
        if dist[j * nx + i] >= 1e9:
            best = None
            for jj in range(max(0, j - 2), min(ny, j + 3)):
                for ii in range(max(0, i - 2), min(nx, i + 3)):
                    dv = dist[jj * nx + ii]
                    if dv < 1e9 and (best is None or dv < best[0]):
                        best = (dv, ii, jj)
            if best is None:
                return None
            i, j = best[1], best[2]
        climb = 0.0
        for step_i in range(look):
            k = j * nx + i
            bi, bj, bd = i, j, dist[k]
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    ii, jj = i + di, j + dj
                    if (di or dj) and 0 <= ii < nx and 0 <= jj < ny:
                        dv = dist[jj * nx + ii]
                        if dv < bd:
                            bi, bj, bd = ii, jj, dv
            if (bi, bj) == (i, j):
                break
            i, j = bi, bj
            if step_i < 2 and self.jet[j * nx + i]:
                climb = max(climb, self.top_abs[j * nx + i] - z)
        cx, cy = self.center(i, j)
        return cx, cy, (climb if climb > 0.8 else 0.0)


def _inside(ring, x, y):
    hit = False
    n = len(ring)
    for a in range(0, n, 2):
        b = (a + 2) % n
        ay, by = ring[a + 1], ring[b + 1]
        if (ay > y) != (by > y) and x < (ring[b] - ring[a]) * (y - ay) / (by - ay) + ring[a]:
            hit = not hit
    return hit


class Bot:
    name = "survivor-v1"

    def __init__(self, hello):
        cfg = hello["config"]
        self.cfg = cfg
        self.rng = random.Random(hello.get("seed", 1))
        self.world = World(hello["map"]["dir"])
        try:
            self.nav = Nav(hello["map"]["dir"])
        except Exception as e:  # navigation is optional: fall back to straight-line zone travel
            mf.log("nav init failed", type(e).__name__, str(e)[:80])
            self.nav = None
        self.nav_jet_until = -1.0
        self.nav_climb = 0.0
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

    # ---------------------------------------------------------------- helpers
    def nav_waypoint(self, x, y, z):
        if self.nav is None:
            return None
        try:
            return self.nav.waypoint(x, y, z)
        except Exception as e:
            mf.log("nav waypoint error", type(e).__name__, str(e)[:80])
            self.nav = None
            return None

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
        nav_used = False
        if self.nav is not None:
            try:
                g = self.nav.goal
                if g is None or math.hypot(g[0] - nzc[0], g[1] - nzc[1]) > 5.0:
                    self.nav.start(nzc[0], nzc[1])
                self.nav.step()
            except Exception as e:
                mf.log("nav error", type(e).__name__, str(e)[:80])
                self.nav = None
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
            wp = self.nav_waypoint(x, y, z)
            tx_, ty_ = toward(wp[0], wp[1]) if wp else toward(zc[0], zc[1])
            nav_used = wp is not None
            if wp and wp[2]:
                self.nav_jet_until = t + 0.6
                self.nav_climb = wp[2]
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
                    if heading_next:
                        wp = self.nav_waypoint(x, y, z)
                        if wp:
                            goal = [wp[0], wp[1]]
                            nav_used = True
                            if wp[2]:
                                self.nav_jet_until = t + 0.6
                                self.nav_climb = wp[2]
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
        elif t < self.nav_jet_until and mode in ("zone", "zone-move"):
            # route crosses a wall we can jet over: climb instead of steering away from it.
            # Start a climb only with enough energy (~1.7 per metre); otherwise wait to recharge.
            need = min(100.0, 1.7 * self.nav_climb + 8.0)
            if me["grounded"] and me["energy"] < need:
                mx = my = 0.0
                mode = "nav-recharge"
            else:
                jump = True
                boost = me["energy"] > 3
                mode = "nav-climb"
        elif moving_cmd > 0.05:
            ang = self.steer(x, y, math.atan2(my, mx))
            n = min(1.0, moving_cmd)
            mx, my = math.cos(ang) * n, math.sin(ang) * n

        # laser charging halves speed anyway; boost only when energy ok
        if boost and me["energy"] < 8:
            boost = False

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

