"""Terrain and prism geometry from the official arena files."""
from __future__ import annotations
import json
import math
import struct
from collections import defaultdict
from pathlib import Path


def inside(ring, x, y):
    hit = False
    for i in range(0, len(ring), 2):
        j = (i + 2) % len(ring)
        ax, ay, bx, by = ring[i], ring[i+1], ring[j], ring[j+1]
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            hit = not hit
    return hit


def crossing(ax, ay, bx, by, cx, cy, dx, dy):
    rx, ry, sx, sy = bx-ax, by-ay, dx-cx, dy-cy
    den = rx*sy-ry*sx
    if abs(den) < 1e-10:
        return None
    qx, qy = cx-ax, cy-ay
    t = (qx*sy-qy*sx)/den
    u = (qx*ry-qy*rx)/den
    return t if 0 <= t <= 1 and 0 <= u <= 1 else None


class World:
    def __init__(self, map_dir):
        self.map_dir = Path(map_dir).resolve()
        data = json.loads((self.map_dir/'v2/world.json').read_text())
        self.bounds = data['bounds']
        self.terrain_meta = data['terrain']
        n = self.terrain_meta['nx'] * self.terrain_meta['ny']
        raw = (self.map_dir/'v2/terrain.i16').read_bytes()
        self.heights = struct.unpack('<'+str(n)+'h', raw)
        self.prisms = []
        self.grid = defaultdict(set)
        self.cell = 32
        for entry in data['prisms']:
            ring = entry['ring']
            holes = entry.get('holes') or []
            edges = []
            for poly in [ring] + holes:
                for i in range(0, len(poly), 2):
                    j = (i+2) % len(poly)
                    edges.append((poly[i], poly[i+1], poly[j], poly[j+1]))
            xs, ys = ring[::2], ring[1::2]
            box = min(xs), min(ys), max(xs), max(ys)
            item = (box, entry['base'], entry['top'], ring, holes, edges)
            idx = len(self.prisms)
            self.prisms.append(item)
            for ix in range(math.floor(box[0]/self.cell), math.floor(box[2]/self.cell)+1):
                for iy in range(math.floor(box[1]/self.cell), math.floor(box[3]/self.cell)+1):
                    self.grid[ix,iy].add(idx)
        tree = data['trees']; fields = tree['fields']; flat = tree['data']; width = len(fields)
        self.trees = [dict(zip(fields, flat[i:i+width])) for i in range(0,len(flat),width)]

    def nearby(self, x, y, radius=0):
        c=self.cell
        result=set()
        for ix in range(math.floor((x-radius)/c), math.floor((x+radius)/c)+1):
            for iy in range(math.floor((y-radius)/c), math.floor((y+radius)/c)+1):
                result.update(self.grid.get((ix,iy), ()))
        return (self.prisms[i] for i in result)

    def terrain(self,x,y):
        m=self.terrain_meta
        gx=max(0,min(m['nx']-1.001,(x-m['minX'])/m['step']))
        gy=max(0,min(m['ny']-1.001,(y-m['minY'])/m['step']))
        i,j=int(gx),int(gy); fx,fy=gx-i,gy-j; nx=m['nx']; h=self.heights
        a=h[j*nx+i]*(1-fx)+h[j*nx+i+1]*fx
        b=h[(j+1)*nx+i]*(1-fx)+h[(j+1)*nx+i+1]*fx
        return (a*(1-fy)+b*fy)*m['scale']

    def solid(self,x,y,z):
        for box,base,top,ring,holes,_ in self.nearby(x,y):
            if base <= z < top and box[0]<=x<=box[2] and box[1]<=y<=box[3] and inside(ring,x,y) and not any(inside(h,x,y) for h in holes):
                return True
        return False

    def floor(self,x,y,feet=None):
        ground=self.terrain(x,y)
        for box,base,top,ring,holes,_ in self.nearby(x,y):
            if feet is not None and top>feet+1.2:
                continue
            if top>ground and box[0]<=x<=box[2] and box[1]<=y<=box[3] and inside(ring,x,y) and not any(inside(h,x,y) for h in holes):
                ground=max(ground,top)
        return ground

    def open_spawn(self,x,y):
        b=self.bounds
        if not (b['minX']+10<x<b['maxX']-10 and b['minY']+10<y<b['maxY']-10):
            return False
        return not self.solid(x,y,self.terrain(x,y)+2.5)

    def line_block(self,a,b):
        ax,ay,az=a; bx,by,bz=b
        if min(az,bz) < min(self.terrain(ax,ay),self.terrain(bx,by))-1:
            return True
        length=math.hypot(bx-ax,by-ay)
        candidates={id(p):p for n in range(max(1,int(length/20)+1)) for p in self.nearby(ax+(bx-ax)*n/max(1,int(length/20)),ay+(by-ay)*n/max(1,int(length/20)),20)}
        for box,base,top,ring,holes,edges in candidates.values():
            if max(ax,bx)<box[0] or min(ax,bx)>box[2] or max(ay,by)<box[1] or min(ay,by)>box[3]:
                continue
            for e in edges:
                if max(ax,bx)<min(e[0],e[2]) or min(ax,bx)>max(e[0],e[2]) or max(ay,by)<min(e[1],e[3]) or min(ay,by)>max(e[1],e[3]):
                    continue
                t=crossing(ax,ay,bx,by,*e)
                if t is not None and 0<t<1 and base<=az+(bz-az)*t<=top:
                    return True
        for n in range(1,max(1,int(length/8))):
            t=n/max(1,int(length/8)); x=ax+(bx-ax)*t; y=ay+(by-ay)*t
            if az+(bz-az)*t<self.terrain(x,y):
                return True
        return False

    def slide(self,x,y,z,dx,dy,radius=2.5,step=1.2,slope=50):
        nx,ny=x+dx,y+dy
        b=self.bounds
        nx=max(b['minX']+radius,min(b['maxX']-radius,nx)); ny=max(b['minY']+radius,min(b['maxY']-radius,ny))
        oldfloor=self.floor(x,y,z)
        def clear(px,py):
            floor=self.floor(px,py,z)
            # Rules §7: anything taller than step_up is a wall *unless your feet are already above it*.
            # Compare against the feet (z), not the floor under the mech, so a jetting mech can cross walls.
            base=max(oldfloor,z)
            grounded=z-oldfloor<0.1
            if floor-base>step or (grounded and floor-base>0 and math.degrees(math.atan2(floor-base,max(0.01,math.hypot(px-x,py-y))))>slope):
                return False
            for ox,oy in ((0,0),(radius,0),(-radius,0),(0,radius),(0,-radius)):
                if self.solid(px+ox,py+oy,z+min(step,max(0,floor-z))+1):
                    return False
            return True
        if clear(nx,ny): return nx,ny
        if clear(nx,y): return nx,y
        if clear(x,ny): return x,ny
        return x,y
