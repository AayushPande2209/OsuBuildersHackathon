"""Mech Royale v2: quiet zone positioning, optional roofs, and selective defence."""
import json
import math
import random
import sys
import mechfight as mf

CONFIG = {
    "legacy_strategy": False,
    "stealth": True, "hideouts": False, "roofs": False, "selective_fire": False,
    "evasion": True, "safe_loot": True, "drops": True, "upgrades": True,
    "endgame": True, "stuck_recovery": True, "npc_farm": False,
    "quiet_move": 0.36, "initial_loot_s": 12.0, "loot_radius": 28.0,
    "cube_radius": 15.0, "drop_interest_radius": 55.0,
    "enemy_safe_range": 100.0, "engage_range": 48.0,
    "fire_after_damage_s": 5.0, "flee_hp_fraction": 0.32,
    "flee_enemy_count": 3, "flee_boost_energy": 28.0,
    "roof_min_height": 7.0, "roof_max_rise": 55.0,
    "roof_edge_margin": 4.0, "climb_energy_margin": 24.0,
    "climb_timeout_s": 14.0, "climb_stall_s": 2.5,
    "hide_reselect_s": 6.0, "hide_arrive_radius": 5.0,
    "hide_zone_margin": 15.0, "hide_next_lead_s": 32.0,
    "zone_travel_buffer_s": 12.0, "zone_urgent_energy": 35.0,
    "hide_distance_weight": 0.12, "hide_exposure_weight": 35.0,
    "hide_roof_bonus": 12.0, "hide_center_weight": 0.06,
    "roof_leave_s": 22.0, "log_every_s": 5.0,
    "projectile_dodge_radius": 4.5, "mortar_dodge_radius": 10.0,
    "laser_dodge_range": 150.0, "stuck_ticks": 7,
    "react_unseen": True, "unseen_react_s": 4.0,
}

TAU = math.tau
PICK_PRIORITY = ["armor", "plating", "nanites", "sensors", "gyros", "jets", "capacitor", "reactor",
                 "servos", "gun_damage", "gun_rate", "gun_mag", "gun_velocity",
                 "laser_damage", "laser_charge", "laser_pierce", "lightning_efficiency",
                 "lightning_range", "lightning_chain", "mortar_reload", "mortar_splash", "mortar_velocity"]
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


def point_in_ring(ring, x, y):
    inside = False
    n = len(ring) // 2
    for i in range(n):
        j = (i + 1) % n
        ax, ay, bx, by = ring[2*i], ring[2*i+1], ring[2*j], ring[2*j+1]
        if (ay > y) != (by > y) and x < ax + (y-ay)*(bx-ax)/(by-ay):
            inside = not inside
    return inside


def edge_distance(x, y, edge):
    ax, ay, bx, by = edge
    dx, dy = bx-ax, by-ay
    u = max(0.0, min(1.0, ((x-ax)*dx+(y-ay)*dy)/max(1e-9, dx*dx+dy*dy)))
    return math.hypot(x-ax-u*dx, y-ay-u*dy)


class World:
    def __init__(self, path):
        self.pr = []  # (minx,miny,maxx,maxy,base,top,edges)
        self.roofs = []
        self.ground = []
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
                if p.get("kind") in ("building", "stadium"):
                    self.roofs.append((p, edges, (min(xs), min(ys), max(xs), max(ys))))
        except Exception as e:  # map is optional
            mf.log("map load failed", e)
        self.near = []
        self.hideouts = self.build_hideouts()

    # Map and hideout geometry (§7, §8, §9). All ray work happens at hello time.
    def solid_xy(self, x, y, z):
        for p, _, box in self.roofs:
            if box[0] <= x <= box[2] and box[1] <= y <= box[3] and p["base"] <= z < p["top"]:
                if point_in_ring(p["ring"], x, y) and not any(point_in_ring(h, x, y) for h in p.get("holes") or []):
                    return True
        return False

    def exposure(self, x, y, z):
        blocked = 0
        for i in range(8):
            a = i * TAU / 8
            dx, dy = math.cos(a), math.sin(a)
            for q in self.pr:
                if q[4] > z+8 or q[5] < z+2 or q[0] > x+200 or q[2] < x-200 or q[1] > y+200 or q[3] < y-200:
                    continue
                if any((t is not None and 0 < t < 200) for t in (seg_hit(x,y,dx,dy,*e) for e in q[6])):
                    blocked += 1
                    break
        return 1.0 - blocked/8.0

    def build_hideouts(self):
        out = []
        # Ground alcoves just outside prism corners; reject solid centers.
        for p, edges, box in self.roofs:
            ring = p["ring"]
            if len(ring) < 6:
                continue
            cx = sum(ring[::2])/len(ring[::2]); cy = sum(ring[1::2])/len(ring[1::2])
            vertices=len(ring)//2
            for i in sorted({2*(j*vertices//min(4,vertices)) for j in range(min(4,vertices))}):
                vx, vy = ring[i]-cx, ring[i+1]-cy
                d = math.hypot(vx,vy)
                if d < 1: continue
                gx, gy = ring[i]+vx/d*5, ring[i+1]+vy/d*5
                if not self.solid_xy(gx,gy,p["base"]+2):
                    out.append((gx,gy,p["base"],"ground",self.exposure(gx,gy,p["base"]),None))
            # Sample interior points and require cylinder clearance from all edges.
            if p["top"]-p["base"] < CONFIG["roof_min_height"] or p["top"]-p["base"] > CONFIG["roof_max_rise"]:
                continue
            best = None
            for fy in (0.25,0.4,0.5,0.6,0.75):
                for fx in (0.25,0.4,0.5,0.6,0.75):
                    x=box[0]+(box[2]-box[0])*fx; y=box[1]+(box[3]-box[1])*fy
                    if not point_in_ring(ring,x,y) or any(point_in_ring(h,x,y) for h in p.get("holes") or []):
                        continue
                    margin=min(edge_distance(x,y,e) for e in edges)
                    if margin >= CONFIG["roof_edge_margin"] and (best is None or margin>best[0]):
                        best=(margin,x,y)
            if best:
                _,x,y=best
                # Approach from the nearest outer edge, then jet toward the roof interior.
                edge=min(edges[:len(ring)//2],key=lambda e:edge_distance(x,y,e))
                mx,my=(edge[0]+edge[2])/2,(edge[1]+edge[3])/2
                vx,vy=mx-x,my-y; d=max(1e-6,math.hypot(vx,vy))
                base=(mx+vx/d*8,my+vy/d*8)
                if self.solid_xy(base[0],base[1],p["base"]+2):
                    base=(mx-vx/d*8,my-vy/d*8)
                out.append((x,y,p["top"],"roof",self.exposure(x,y,p["top"]),base))
        # Keep lowest exposure candidates to bound per-tick ranking work.
        ground=sorted((h for h in out if h[3]=="ground"),key=lambda h:h[4])[:180]
        roof=[h for h in out if h[3]=="roof"]
        return ground+roof

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
    name = "survivor-v2"

    def __init__(self, hello):
        cfg = hello["config"]
        self.cfg = cfg
        self.rng = random.Random(hello.get("seed", 1))
        self.world = World(hello["map"]["dir"])
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
        self.hideout = None
        self.hide_selected_at = -99.0
        self.failed_roofs = set()
        self.climb_started = -99.0
        self.climb_progress_at = -99.0
        self.climb_top_z = -1e6
        self.damaged_at = -99.0
        self.damage_bearing = None
        self.last_log = -99.0

    # Hideout selection (§7-9): use the announced next circle, cached exposure,
    # distance and roof advantage; re-rank only every few seconds.
    def choose_hideout(self, x, y, z, me, zone, t):
        if not CONFIG["hideouts"] or not self.world.hideouts:
            return None
        next_center = zone.get("next_center", zone["center"])
        next_radius = zone.get("next_radius", zone["radius"])
        now_center, now_radius = self.zone_now(zone,t)
        next_known = t >= zone.get("shrink_start",1e9)-CONFIG["hide_next_lead_s"]
        next_known |= math.hypot(x-next_center[0],y-next_center[1]) > next_radius-10
        center = next_center if next_known else now_center
        radius = next_radius if next_known else now_radius
        if (self.hideout is not None and t-self.hide_selected_at < CONFIG["hide_reselect_s"]
                and math.hypot(self.hideout[0]-center[0],self.hideout[1]-center[1]) < radius-CONFIG["hide_zone_margin"]
                and (self.hideout[3] != "roof" or self.hideout[:2] not in self.failed_roofs)):
            return self.hideout
        best = None
        best_score = 1e12
        for h in self.world.hideouts:
            hx,hy,hz,kind,exposure,base=h
            dc=math.hypot(hx-center[0],hy-center[1])
            if dc > radius-CONFIG["hide_zone_margin"]:
                continue
            if kind=="roof":
                if not CONFIG["roofs"] or h[:2] in self.failed_roofs or hz-z > CONFIG["roof_max_rise"]:
                    continue
                if me.get("energy",0) < CONFIG["climb_energy_margin"]+25 and z<hz-3:
                    continue
                # Late-zone roofs become a liability when the next circle moves.
                if t > zone.get("shrink_start",1e9)-CONFIG["roof_leave_s"] and dc > next_radius*0.65:
                    continue
            distance=math.hypot(hx-x,hy-y)
            if kind=="roof" and z<hz-3 and base is not None:
                distance=math.hypot(base[0]-x,base[1]-y)+hz-z
            score=(CONFIG["hide_distance_weight"]*distance +
                   CONFIG["hide_exposure_weight"]*exposure +
                   CONFIG["hide_center_weight"]*dc -
                   (CONFIG["hide_roof_bonus"] if kind=="roof" else 0))
            if score<best_score:
                best_score=score;best=h
        self.hideout=best
        self.hide_selected_at=t
        return best

    # Roof climb (§7): approach wall, jump/jet until feet clear, then enter.
    def climb_move(self, h, me, t):
        x,y,z=me["pos"]; hx,hy,hz,_,_,base=h
        if z>=hz-0.8 and math.hypot(hx-x,hy-y)<CONFIG["hide_arrive_radius"]:
            self.climb_started=-99.0
            return 0.0,0.0,False,False,"hide-roof"
        if base is not None and (z<hz+1.5 or self.climb_started>=0):
            bx,by=base; d=math.hypot(x-bx,y-by)
            if d>3.0 and self.climb_started<0:
                a=math.atan2(by-y,bx-x)
                pace=CONFIG["quiet_move"] if CONFIG["stealth"] else 1.0
                return math.cos(a)*pace,math.sin(a)*pace,False,False,"roof-approach"
            if self.climb_started<0:
                self.climb_started=t; self.climb_progress_at=t;self.climb_top_z=z
            if z>self.climb_top_z+0.8:
                self.climb_top_z=z;self.climb_progress_at=t
            if (t-self.climb_started>CONFIG["climb_timeout_s"] or
                (z<hz+1.5 and t-self.climb_progress_at>CONFIG["climb_stall_s"]) or
                me.get("energy",0)<CONFIG["climb_energy_margin"]):
                self.failed_roofs.add(h[:2]);self.hideout=None;self.climb_started=-99.0
                return 0.0,0.0,False,False,"roof-abort"
            # Rise clear of the wall before moving inward, then stay aloft
            # until the center has passed the outside roof edge.
            if z<hz+1.5:
                return 0.0,0.0,not me.get("grounded",False),bool(me.get("grounded",False)),"roof-climb"
            a=math.atan2(hy-y,hx-x)
            crossed=math.hypot(hx-x,hy-y)<math.hypot(hx-bx,hy-by)-8
            if not crossed:
                return math.cos(a),math.sin(a),not me.get("grounded",False),False,"roof-enter"
        self.climb_started=-99.0
        a=math.atan2(hy-y,hx-x)
        return math.cos(a)*0.55,math.sin(a)*0.55,False,False,"roof-enter"

    # Evasion (§7): react only to trajectories that could hit the cylinder.
    def evasion_move(self, obs, me, x, y, z):
        if not CONFIG["evasion"]:
            return None
        for pr in obs.get("projectiles",[]):
            p=pr.get("pos",());v=pr.get("vel",())
            if len(p)<3 or len(v)<3:
                continue
            vx,vy,vz=v; speed2=vx*vx+vy*vy
            if speed2<1:
                continue
            if pr.get("kind")=="mortar":
                gravity=self.cfg.get("weapons",{}).get("mortar",{}).get("gravity",22)
                height=p[2]-z
                disc=vz*vz+2*gravity*height
                if disc<0:continue
                impact_t=(vz+math.sqrt(disc))/max(1e-6,gravity)
                if not 0<impact_t<2.0:continue
                ix,iy=p[0]+vx*impact_t,p[1]+vy*impact_t
                dx,dy=x-ix,y-iy; d=math.hypot(dx,dy)
                if d<CONFIG["mortar_dodge_radius"]:
                    if d<1:
                        dx,dy=-vy,vx;d=max(1,math.hypot(dx,dy))
                    return dx/d,dy/d,True,"dodge-mortar"
            else:
                rx,ry=x-p[0],y-p[1]
                hit_t=(rx*vx+ry*vy)/speed2
                if not 0<hit_t<0.35:continue
                miss=math.hypot(p[0]+vx*hit_t-x,p[1]+vy*hit_t-y)
                zh=p[2]+vz*hit_t
                if miss<CONFIG["projectile_dodge_radius"] and z-2<zh<z+11:
                    side=1 if (rx*vy-ry*vx)>0 else -1
                    speed=math.sqrt(speed2)
                    return -vy/speed*side,vx/speed*side,False,"dodge-gun"
        for enemy in obs.get("mechs",[]):
            if enemy.get("kind")!="mech" or not enemy.get("charging"):
                continue
            p=enemy.get("pos",());
            if len(p)<2:continue
            dx,dy=x-p[0],y-p[1];d=math.hypot(dx,dy)
            if d>CONFIG["laser_dodge_range"] or d<1:continue
            bearing=math.atan2(dy,dx)
            if abs(wrap(bearing-enemy.get("aim",[0])[0]))<0.17:
                side=1 if (me["id"]+enemy["id"])%2 else -1
                return -dy/d*side,dx/d*side,False,"dodge-laser"
        return None

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

    # Reliability (§2, §6): always answer, including a pending upgrade.
    def act(self, obs):
        try:
            return self._act(obs)
        except Exception as exc:
            if obs.get("t",0)-self.last_log>CONFIG["log_every_s"]:
                mf.log("v2 fallback",type(exc).__name__,str(exc)[:100])
                self.last_log=obs.get("t",0)
            answer={"tick":obs.get("tick",0),"move":[0,0],"boost":False,"fire":[False,False]}
            if obs.get("offer"):
                answer["pick"]=0
            return answer

    # Decision loop; all costly map geometry was cached at hello time.
    def _act(self, obs):
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
        if obs.get("offer"):
            ids = [c.get("id") for c in obs["offer"].get("choices",[])]
            if ids:
                carried=[w.get("kind") for w in me.get("weapons",[]) if w]
                weapon_priority=[f"{kind}_{suffix}" for kind in carried
                    for suffix in ("damage","charge","rate","reload","efficiency","range","splash","chain","mag","velocity","pierce")]
                priority=(PICK_PRIORITY[:8]+weapon_priority+PICK_PRIORITY[8:]) if CONFIG["upgrades"] else []
                act["pick"] = min(range(len(ids)),key=lambda i: priority.index(ids[i]) if ids[i] in priority else 99)

        for event in obs.get("events",[]):
            if event.get("type")=="damaged" and event.get("weapon")!="zone":
                self.damaged_at=t
                if event.get("bearing") is not None:
                    self.damage_bearing=event["bearing"]

        # stuck detection
        speed = math.hypot(me["vel"][0], me["vel"][1])

        # sounds
        for s in obs.get("sounds",[]):
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
        safe_take = not CONFIG["safe_loot"] or (not close and t-self.damaged_at>CONFIG["fire_after_damage_s"])
        for p in sorted(near_pick if safe_take else [], key=lambda p: -WEAPON_RANK.get(p["kind"], 0)):
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
        if target is None and npcs and hp_frac > 0.8 and (CONFIG["npc_farm"] or not CONFIG["stealth"]) and t<70:
            n0 = min(npcs, key=lambda m: d2(m["pos"]))
            if d2(n0["pos"]) < 70:
                target = n0
        tgt_d = None
        if target is not None and (not CONFIG["selective_fire"] or
            (target["kind"]=="mech" and (d2(target["pos"])<CONFIG["engage_range"] or
             t-self.damaged_at<CONFIG["fire_after_damage_s"]))):
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
        if not close and g_ammo_low(me) and (not CONFIG["stealth"] or t-self.damaged_at<CONFIG["fire_after_damage_s"]):
            act["reload"] = True

        # ---------------- movement
        mx, my = 0.0, 0.0
        boost = False
        jump = False
        mode = "idle"

        def toward(px, py, w=1.0):
            a = math.atan2(py - y, px - x)
            return math.cos(a) * w, math.sin(a) * w

        quiet_pace=CONFIG["quiet_move"] if CONFIG["stealth"] else 1.0

        outside = (not me.get("in_zone", True)) or dz_center > zr - 7
        threatened = bool(close and d2(close[0]["pos"]) < CONFIG["engage_range"])
        threatened |= t-self.damaged_at < CONFIG["fire_after_damage_s"]
        if outside:
            mode="zone"
            mx,my=toward(zc[0],zc[1])
            boost=me["energy"]>CONFIG["flee_boost_energy"] and dz_center>zr+10
        elif threatened and target is not None and tgt_d is not None:
            ex,ey=target["pos"][0]-x,target["pos"][1]-y
            ed=max(1e-6,math.hypot(ex,ey));rx,ry=ex/ed,ey/ed
            n_threat=sum(d2(m["pos"])<CONFIG["enemy_safe_range"] for m in mechs)
            flee=hp_frac<CONFIG["flee_hp_fraction"] or n_threat>=CONFIG["flee_enemy_count"]
            if t>self.strafe_until:
                self.strafe=-self.strafe;self.strafe_until=t+1.2
            # Face the attacker, use lateral motion, and bias retreat toward zone safety.
            mx,my=-ry*self.strafe,rx*self.strafe
            if flee:
                mx-=rx*0.8;my-=ry*0.8;mode="flee"
                boost=me["energy"]>CONFIG["flee_boost_energy"] and ed<70
            else:
                mode="fight"
            if dn_center>nzr-15:
                zx,zy=toward(nzc[0],nzc[1],0.35)
                mx+=zx;my+=zy
        elif (CONFIG["react_unseen"] and self.damage_bearing is not None
              and t-self.damaged_at < CONFIG["unseen_react_s"]):
            # Shot from outside view: don't sit still. Run away from the shot's origin,
            # biased toward the zone, with a lateral wobble so we are hard to track.
            mode="evade-unseen"
            ax,ay=-math.cos(self.damage_bearing),-math.sin(self.damage_bearing)
            if t>self.strafe_until:
                self.strafe=-self.strafe;self.strafe_until=t+1.0
            mx,my=ax-ay*0.5*self.strafe,ay+ax*0.5*self.strafe
            zx,zy=toward(nzc[0],nzc[1],0.35)
            mx+=zx;my+=zy
            boost=me["energy"]>CONFIG["flee_boost_energy"] and hp_frac<0.6
        else:
            # Quiet loot is limited to the spawn period or a short safe detour.
            goal=None
            safe=not any(d2(m["pos"])<CONFIG["enemy_safe_range"] for m in mechs)
            if CONFIG["safe_loot"] and safe and t<CONFIG["initial_loot_s"]:
                pk=[p for p in obs.get("pickups",[]) if p.get("kind") in WEAPON_RANK and p["kind"] not in wk
                    and d2(p["pos"])<CONFIG["loot_radius"] and abs(p["pos"][2]-z)<4]
                if pk and None in wk:
                    goal=min(pk,key=lambda p:d2(p["pos"])/WEAPON_RANK[p["kind"]])["pos"];mode="loot"
            if goal is None and CONFIG["safe_loot"] and safe:
                cu=[c for c in obs.get("cubes",[]) if d2(c["pos"])<CONFIG["cube_radius"] and abs(c["pos"][2]-z)<4]
                if cu:
                    goal=min(cu,key=lambda c:d2(c["pos"]))["pos"];mode="cube"
            if goal is None and CONFIG["drops"] and safe and hp_frac<0.75:
                for dr in obs.get("drops",[]):
                    dd=d2(dr["pos"])
                    if dd<CONFIG["drop_interest_radius"] and dr.get("lands_in",99)<dd/10+5 and dr.get("holder") in (None,me["id"]):
                        if not any(math.hypot(m["pos"][0]-dr["pos"][0],m["pos"][1]-dr["pos"][1])<CONFIG["enemy_safe_range"] for m in mechs):
                            goal=dr["pos"];mode="drop"
                            break
            if goal is None:
                wait_late=(CONFIG["endgame"] and obs.get("alive",16)<=4 and t>210 and
                    dn_center<nzr*0.55 and not threatened and me.get("in_zone",True) and
                    (self.hideout is None or math.hypot(self.hideout[0]-x,self.hideout[1]-y)<CONFIG["hide_arrive_radius"]))
                h=None if wait_late else self.choose_hideout(x,y,z,me,obs["zone"],t)
                if h is not None:
                    if h[3]=="roof":
                        mx,my,boost,jump,mode=self.climb_move(h,me,t)
                    else:
                        self.climb_started=-99.0
                        d=math.hypot(h[0]-x,h[1]-y)
                        if d>CONFIG["hide_arrive_radius"]:
                            mx,my=toward(h[0],h[1],quiet_pace);mode="hide-move"
                        else:
                            mode="hide-ground"
                elif dn_center>nzr-12:
                    goal=nzc;mode="zone-next"
                elif wait_late:
                    mode="endgame-wait"
            if goal is not None:
                d=math.hypot(goal[0]-x,goal[1]-y)
                if d>2.5:
                    mx,my=toward(goal[0],goal[1],quiet_pace if mode in ("loot","cube") else 0.8)
                elif mode=="drop":
                    mode="hold-drop"

        # Zone urgency (§9): quiet walking cannot outrun a distant closing circle.
        if CONFIG["endgame"] and mode in ("hide-move","roof-approach","roof-enter","zone-next"):
            next_out=max(0.0,dn_center-nzr+CONFIG["hide_zone_margin"])
            time_left=max(0.0,obs["zone"].get("shrink_end",t)-t)
            if next_out>0 and next_out/max(1.0,stats.get("walk_speed",11.7)*quiet_pace)+CONFIG["zone_travel_buffer_s"]>time_left:
                dmove=math.hypot(mx,my)
                if dmove>0.01:
                    mx,my=mx/dmove,my/dmove
                else:
                    mx,my=toward(nzc[0],nzc[1])
                boost=me["energy"]>CONFIG["zone_urgent_energy"] and next_out>30
                mode="zone-urgent"

        dodge=self.evasion_move(obs,me,x,y,z)
        if dodge is not None:
            mx,my,evade_boost,mode=dodge
            boost=evade_boost and me["energy"]>CONFIG["flee_boost_energy"]
            jump=mode=="dodge-mortar" and me.get("grounded",False)

        # stuck / escape
        moving_cmd = math.hypot(mx, my)
        if moving_cmd > 0.1 and speed < 1.5 and me["grounded"] and mode not in ("roof-climb","roof-enter","hide-roof"):
            self.stuck += 1
        else:
            self.stuck = max(0, self.stuck - 1)
        if CONFIG["stuck_recovery"] and self.stuck >= CONFIG["stuck_ticks"] and t > self.escape_until:
            self.escape_until = t + 1.2
            self.escape_dir = self.rng.uniform(-math.pi, math.pi)
            self.stuck = 0
        if t < self.escape_until:
            mx, my = math.cos(self.escape_dir), math.sin(self.escape_dir)
            jump = True
            boost = me["energy"] > CONFIG["flee_boost_energy"] and (outside or threatened)
            mode = "escape"
        elif moving_cmd > 0.05 and mode not in ("roof-climb","roof-enter"):
            ang = self.steer(x, y, math.atan2(my, mx))
            n = min(1.0, moving_cmd)
            mx, my = math.cos(ang) * n, math.sin(ang) * n

        # laser charging halves speed anyway; boost only when energy ok
        if boost and me["energy"] < 8:
            boost = False

        # ---------------- aim when no target: scan toward sounds, else slow sweep
        if aim is None:
            recent_damage=next((e for e in reversed(obs.get("events",[])) if e.get("type")=="damaged" and e.get("bearing") is not None),None)
            if recent_damage is not None:
                aim=[recent_damage["bearing"],0.0]
            elif self.sound_bearing is not None and t - self.sound_t < 3:
                aim = [self.sound_bearing, 0.0]
            elif moving_cmd > 0.3 and mode in ("zone", "zone-move", "loot", "cube", "drop", "escape"):
                aim = [math.atan2(my, mx), 0.0]
            elif not CONFIG["stealth"]:
                aim = [me["aim"][0]+0.5,0.0]
            else:
                aim = [me["aim"][0], me["aim"][1]]

        if t-self.last_log >= CONFIG["log_every_s"]:
            mf.log(f"v2 t={t:.1f} mode={mode} hp={me['hp']:.0f} en={me['energy']:.0f} alive={obs.get('alive',0)}")
            self.last_log=t

        act.update(move=[round(mx, 3), round(my, 3)], boost=boost, jump=jump,
                   aim=[round(wrap(aim[0]), 4), round(aim[1], 4)], fire=fire)
        mf.draw.label(f"{mode} hp{me['hp']:.0f}")
        return act


def g_ammo_low(me):
    w = me["weapons"][0]
    return bool(w and w["kind"] == "gun" and w.get("ammo", 99) < 6 and w.get("reload", 0) <= 0)


if CONFIG["legacy_strategy"]:
    from bot_v1 import SafeBot as ActiveBot
else:
    ActiveBot = Bot

mf.run(ActiveBot)
