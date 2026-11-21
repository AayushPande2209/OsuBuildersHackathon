"""Summarize recorded deaths and damage context."""
import argparse
import json
from collections import Counter
from pathlib import Path
from protocol import ROOT

def summarize(directory):
    files=sorted(Path(directory).glob('match_*.jsonl'))
    causes=Counter();rear=hits=weapon_hits=idle=0;first=[];at_death=[];deaths=0
    for path in files:
        frames=[json.loads(line) for line in path.open()]
        if not frames or not frames[-1].get('end'):continue
        end=frames[-1];frames=frames[:-1]
        if end['weapon'] is not None:
            deaths+=1;causes[end['weapon']]+=1
            if frames:at_death.append(len(frames[-1]['visible']))
        seen_first=False
        for f in frames:
            if f['damage'] and not seen_first:first.append(f['t']);seen_first=True
            for event in f['damage']:
                hits+=1
                if event.get('weapon')!='zone':
                    weapon_hits+=1;rear+=bool(event.get('rear'))
                act=f.get('action') or {};move=act.get('move') or [0,0]
                idle+=move[0]**2+move[1]**2<0.01
    print(f'files: {len(files)}; deaths: {deaths}; causes: {dict(causes)}')
    print(f'rear weapon hits: {rear}/{weapon_hits} ({rear/max(1,weapon_hits):.1%}); idle when hit: {idle}/{hits} ({idle/max(1,hits):.1%})')
    print(f'time to first damage: {sum(first)/len(first):.1f}s' if first else 'time to first damage: n/a')
    print(f'visible enemies at death: {sum(at_death)/len(at_death):.1f}' if at_death else 'visible enemies at death: n/a')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',nargs='?',default=str(ROOT/'out'));summarize(p.parse_args().directory)
