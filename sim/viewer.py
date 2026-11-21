"""Write a self-contained HTML canvas replay from a compact match JSONL."""
import argparse
import json
from pathlib import Path
from protocol import KIT

def render(src,dst):
    frames=[json.loads(line) for line in Path(src).open() if line.strip()]
    frames=[f for f in frames if not f.get('end')]
    world=json.loads((KIT/'arena/v2/world.json').read_text())
    footprints=[p['ring'] for p in world['prisms']]
    b=world['bounds']; payload=json.dumps({'frames':frames,'footprints':footprints,'bounds':b},separators=(',',':'))
    html='''<!doctype html><meta charset="utf-8"><title>Mech Royale replay</title><style>body{background:#111;color:white;font:14px sans-serif}canvas{border:1px solid #555}button,input{margin:8px}</style><h1>Mech Royale replay</h1><button id="play">Pause</button><input id="seek" type="range" min="0" value="0"><span id="label"></span><br><canvas id="map" width="1000" height="680"></canvas><script>const data=PAYLOAD;const c=document.getElementById('map'),x=c.getContext('2d'),seek=document.getElementById('seek');let i=0,running=true;seek.max=Math.max(0,data.frames.length-1);const b=data.bounds,sx=c.width/(b.maxX-b.minX),sy=c.height/(b.maxY-b.minY);function X(v){return(v-b.minX)*sx}function Y(v){return c.height-(v-b.minY)*sy}function dot(p,r,color){x.fillStyle=color;x.beginPath();x.arc(X(p[0]),Y(p[1]),r,0,7);x.fill()}function draw(){if(!data.frames.length)return;const f=data.frames[i];x.fillStyle='#182326';x.fillRect(0,0,c.width,c.height);x.strokeStyle='#34474a';x.lineWidth=1;for(const ring of data.footprints){x.beginPath();for(let j=0;j<ring.length;j+=2){if(j)x.lineTo(X(ring[j]),Y(ring[j+1]));else x.moveTo(X(ring[j]),Y(ring[j+1]))}x.closePath();x.stroke()}x.strokeStyle='#46b9e6';x.lineWidth=2;x.beginPath();x.arc(X(f.zone.center[0]),Y(f.zone.center[1]),f.zone.radius*(sx+sy)/2,0,7);x.stroke();for(const m of f.visible)dot(m.pos,5,'#ff6a50');for(const p of f.projectiles)dot(p.pos,2,'#ffe286');dot(f.pos,6,'#63f4b7');document.getElementById('label').textContent=`${f.t.toFixed(1)} s · HP ${f.hp.toFixed(0)} · visible ${f.visible.length}`;seek.value=i}document.getElementById('play').onclick=()=>{running=!running;document.getElementById('play').textContent=running?'Pause':'Play'};seek.oninput=()=>{i=+seek.value;draw()};setInterval(()=>{if(running){i=Math.min(i+1,data.frames.length-1);draw()}},50);draw()</script>'''
    Path(dst).write_text(html.replace('PAYLOAD',payload))
    print(dst)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('match');p.add_argument('-o','--output');a=p.parse_args();render(a.match,a.output or str(Path(a.match).with_suffix('.html')))
