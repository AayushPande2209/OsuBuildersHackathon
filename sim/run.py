"""Parallel offline match runner. Run from any working directory."""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import math
import os
import selectors
import shlex
import subprocess
import sys
import time
from pathlib import Path
from engine import Engine
from house import Squad, KNOBS
from protocol import KIT, ROOT, validate

class BotProcess:
    def __init__(self,command,hello,relaxed=False):
        self.p=subprocess.Popen(shlex.split(command),cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,bufsize=0)
        self.fd=self.p.stdout.fileno();self.selector=selectors.DefaultSelector();self.selector.register(self.fd,selectors.EVENT_READ)
        self.buffer=b'';self.relaxed=relaxed;self.crashed=False
        self.send(hello)
        msg=self.read(20 if relaxed else hello['config']['bot']['hello_budget_ms']/1000)
        if not msg or msg.get('type')!='ready':self.crashed=True
        else:
            try:validate('Ready',msg)
            except ValueError:self.crashed=True
    def send(self,msg):
        try:self.p.stdin.write((json.dumps(msg,separators=(',',':'))+'\n').encode());self.p.stdin.flush()
        except (BrokenPipeError,OSError):self.crashed=True
    def read(self,timeout):
        deadline=time.monotonic()+timeout
        while True:
            if b'\n' in self.buffer:
                line,self.buffer=self.buffer.split(b'\n',1)
                if len(line)>65536:continue
                try:return json.loads(line)
                except (json.JSONDecodeError,UnicodeDecodeError):continue
            if self.p.poll() is not None:self.crashed=True;return None
            wait=max(0,deadline-time.monotonic())
            if wait==0:return None
            if not self.selector.select(wait):return None
            data=os.read(self.fd,65536)
            if not data:self.crashed=True;return None
            self.buffer+=data
            if len(self.buffer)>131072:self.buffer=self.buffer[-65536:]
    def action(self,obs):
        if self.crashed:return None
        self.send(obs)
        if self.crashed:return None
        budget=None if self.relaxed else 0.05
        deadline=time.monotonic()+(10 if budget is None else budget)
        while time.monotonic()<deadline:
            msg=self.read(max(0.0001,deadline-time.monotonic()))
            if msg is None:return None
            try:validate('Action',msg)
            except ValueError:continue
            if msg.get('tick')==obs['tick']:return msg
        return None
    def close(self,end):
        validate('EndMsg',end)
        if self.p.poll() is None:
            self.send(end)
            try:self.p.stdin.close();self.p.wait(timeout=1)
            except (subprocess.TimeoutExpired,OSError):self.p.kill();self.p.wait()
        self.selector.close()


def single(args):
    index,seed,slot,bot,map_dir,out_dir,relaxed,validate_messages,knobs=args
    engine=Engine(seed,slot,map_dir,validate_messages=validate_messages)
    squad=Squad(seed,slot,knobs)
    proc=BotProcess(bot,engine.hello(),relaxed)
    path=Path(out_dir)/f'match_{index}.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    curve=[];first_damage=None
    with path.open('w') as log:
        while not engine.done() and engine.me[slot]['alive']:
            if engine.me[slot]['alive']:
                obs=engine.observation(slot)
                if first_damage is None and any(e['type']=='damaged' for e in obs['events']):first_damage=engine.t
                act=proc.action(obs)
                if proc.crashed:engine.me[slot]['crashed']=True
                player=engine.me[slot]
                curve.append(player['hp'])
                log.write(json.dumps({'t':engine.t,'tick':engine.tick,'pos':player['pos'],'hp':player['hp'],
                    'aim':player['aim'],'action':act,'visible':[{'id':m['id'],'pos':m['pos'],'hp':m.get('hp')} for m in obs['mechs']],
                    'damage':[e for e in obs['events'] if e['type']=='damaged'],'zone':obs['zone'],
                    'projectiles':obs['projectiles']},separators=(',',':'))+'\n')
            else:act=None
            houseobs={m['id']:engine.house_observation(m['id']) for m in engine.me if m['id']!=slot and m['alive'] and engine.t>=m.get('house_next',0)}
            actions=squad.decide(engine,houseobs)
            if act is not None:actions[slot]=act
            engine.actions(actions)
            engine.step();engine.step()
        info=engine.finish()
        log.write(json.dumps({'end':True,'place':info['place'],'kills':engine.kills[slot],
                              'time':info['time'],'killer':info['killer'],'weapon':info['weapon']})+'\n')
    proc.close({'type':'end','place':info['place'],'kills':engine.kills[slot]})
    summary={'match':index,'seed':seed,'slot':slot,'place':info['place'],'kills':engine.kills[slot],
             'time':round(info['time'],2),'killer':info['killer'],'weapon':info['weapon'],
             'hp_min':round(min(curve),1) if curve else None,'hp_final':round(engine.me[slot]['hp'],1),
             'first_damage':first_damage,'path':str(path)}
    return summary


def run_many(bot,matches=48,seed=1,jobs=4,slot='random',map_dir=None,out_dir=None,relaxed=False,validate_messages=True,knobs=None):
    out_dir=str(Path(out_dir or ROOT/'out').resolve());map_dir=str(Path(map_dir or KIT/'arena').resolve())
    import random
    rng=random.Random(seed+999)
    tasks=[(i,seed+i, rng.randrange(16) if slot=='random' else int(slot),bot,map_dir,out_dir,relaxed,validate_messages,knobs) for i in range(matches)]
    results=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
        futures=[pool.submit(single,t) for t in tasks]
        for f in concurrent.futures.as_completed(futures):
            r=f.result();results.append(r)
            fate=f"death {r['time']:.1f}s" if r['weapon'] else f"survived {r['time']:.1f}s"
            print(f"match {r['match']}: place {r['place']} kills {r['kills']} {fate} killer {r['killer']} weapon {r['weapon']} HP min/final {r['hp_min']}/{r['hp_final']}",flush=True)
    results.sort(key=lambda r:r['match'])
    scores=[16-r['place'] for r in results];mean=sum(scores)/len(scores)
    se=math.sqrt(sum((v-mean)**2 for v in scores)/(len(scores)-1)/len(scores)) if len(scores)>1 else 0
    hist={place:sum(r['place']==place for r in results) for place in range(1,17)}
    print(f'mean (16 - place): {mean:.3f}; standard error: {se:.3f}')
    print('places: '+' '.join(f'{k}:{v}' for k,v in hist.items()))
    return mean,se,results


def main():
    p=argparse.ArgumentParser();p.add_argument('--bot',default='python3 -u ../bot.py');p.add_argument('--matches',type=int,default=48)
    p.add_argument('--seed',type=int,default=1);p.add_argument('--jobs',type=int,default=4);p.add_argument('--slot',default='random')
    p.add_argument('--map-dir');p.add_argument('--out-dir');p.add_argument('--lockstep-relaxed',action='store_true')
    a=p.parse_args();run_many(a.bot,a.matches,a.seed,a.jobs,a.slot,a.map_dir,a.out_dir,a.lockstep_relaxed)
if __name__=='__main__':main()
