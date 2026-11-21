"""Run both benchmark bots using the same seeds and print honest calibration gaps."""
import argparse
from pathlib import Path
from house import KNOBS
from protocol import KIT,ROOT
from run import run_many

def main():
    p=argparse.ArgumentParser();p.add_argument('--matches',type=int,default=48);p.add_argument('--seed',type=int,default=1);p.add_argument('--jobs',type=int,default=4)
    p.add_argument('--lockstep-relaxed',action='store_true');a=p.parse_args()
    example='python3 -u kit/python/example_bot.py';current='python3 -u ../bot.py'
    print('house knobs:',KNOBS,flush=True)
    x,_,_=run_many(example,a.matches,a.seed,a.jobs,out_dir=ROOT/'out_example',relaxed=a.lockstep_relaxed)
    y,_,_=run_many(current,a.matches,a.seed,a.jobs,out_dir=ROOT/'out_current',relaxed=a.lockstep_relaxed)
    print(f'example score {x:.3f} versus real ~1.15 (gap {x-1.15:+.3f})')
    print(f'current score {y:.3f} versus real ~1.85 (gap {y-1.85:+.3f})')
    if abs(x-1.15)>0.3 or abs(y-1.85)>0.3:
        print('NOT CALIBRATED. Reduce aim_noise_deg and reaction_s to increase combat pressure; increase move_quality to help house bots survive zone travel. Re-run 48 seeds after tuning.')
    else:print('Within 0.3 of both supplied reference means; sampling error still applies.')
if __name__=='__main__':main()
