"""House squad. All decisions use per-bot observations plus shared squad sightings."""
import math
import random
from engine import dist, lead, wrap

# Calibration knobs. Changes here alter the strength of the 15 opponents.
KNOBS = {
    'hunter_start': 1,
    'hunter_ramp_s': 0,
    'hunter_all_s': 240,
    'aim_noise_deg': {'easy': 8, 'medium': 4, 'hard': 1.5, 'expert': 0.5},
    'reaction_s': {'easy': 0.45, 'medium': 0.25, 'hard': 0.12, 'expert': 0.06},
    'lead_fraction': {'easy': 0.1, 'medium': 0.5, 'hard': 0.85, 'expert': 1.0},
    'move_quality': {'easy': 0.3, 'medium': 0.55, 'hard': 0.8, 'expert': 1.0},
    'hunt_memory_s': {'easy': 1, 'medium': 3, 'hard': 6, 'expert': 10},
}

class Squad:
    def __init__(self,seed,player_slot,knobs=None):
        self.player_slot=player_slot;self.rng=random.Random(seed+771)
        self.k=KNOBS.copy();self.k.update(knobs or {})
        ids=[i for i in range(16) if i!=player_slot]
        self.rng.shuffle(ids)
        self.difficulty={i:(['easy']*4+['medium']*4+['hard']*4+['expert']*3)[n] for n,i in enumerate(ids)}
        self.hunt_order=ids
        self.last_seen=None;self.last_seen_at=-99
        self.last_action={}
        self.nav={}
    def decide(self,engine,observations):
        t=engine.t; player=engine.me[self.player_slot]
        visible=[o for o in observations.values() if any(a['id']==self.player_slot for a in o['mechs'])]
        if visible:
            self.last_seen=player['pos'][:];self.last_seen_at=t
        count=int(self.k['hunter_start']+(15-self.k['hunter_start'])*min(1,max(0,(t-self.k['hunter_ramp_s'])/max(1,self.k['hunter_all_s']-self.k['hunter_ramp_s']))))
        if not player['alive']:count=0
        count=max(count,1+len(engine.deaths)//2)
        hunters=set(self.hunt_order[:count]); actions={}
        for id in self.hunt_order:
            m=engine.me[id]; d=self.difficulty[id]; k=self.k
            if not m['alive']:continue
            obs=observations.get(id)
            if obs is None:
                actions[id]={'tick':engine.tick,**self.last_action.get(id,{})};continue
            m['house_next']=t+k['reaction_s'][d]
            me=obs['self'];p=me['pos']; z=obs['zone']; enemies=[a for a in obs['mechs'] if a['kind']=='npc']
            target=next((a for a in obs['mechs'] if a['id']==self.player_slot),None)
            hunting=id in hunters and self.last_seen is not None and t-self.last_seen_at<=k['hunt_memory_s'][d]
            if hunting:
                goal=self.last_seen; target=target or {'pos':goal,'vel':[0,0,0],'id':self.player_slot,'kind':'mech'}
            else:
                goal=z['next_center'] if t>z['shrink_start']-35 else z['center']
                if me['weapons'][1] is None:
                    loot=[q for q in obs['pickups'] if q['kind']!='gun']
                    if loot:
                        nearest=min(loot,key=lambda q:dist(q['pos'],p))
                        if dist(nearest['pos'],p)<90:goal=nearest['pos']
                if target is None and enemies and d in ('hard','expert'):
                    target=min(enemies,key=lambda a:dist(a['pos'],p))
            gyaw=math.atan2(goal[1]-p[1],goal[0]-p[0]); quality=k['move_quality'][d]
            move=[math.cos(gyaw),math.sin(gyaw)]
            if target and dist(p,target['pos'])<65 and quality>0.5:
                tx,ty=target['pos'][:2]; yaw=math.atan2(ty-p[1],tx-p[0]);side=1 if id%2 else -1
                move=[-math.sin(yaw)*side*quality+move[0]*(1-quality),math.cos(yaw)*side*quality+move[1]*(1-quality)]
            # Keep a detour heading long enough to pass a wall corner.
            if quality>=0.3 and math.hypot(*move)>0.1:
                base=math.atan2(move[1],move[0]);chosen=base
                if id in self.nav and t<self.nav[id][1]:
                    chosen=self.nav[id][0]
                else:
                    for off in (0,0.45,-0.45,0.9,-0.9,1.35,-1.35,1.8,-1.8,2.4,-2.4):
                        a2=base+off;dx=math.cos(a2)*4;dy=math.sin(a2)*4
                        nx,ny=engine.world.slide(p[0],p[1],p[2],dx,dy,me['stats']['radius'])
                        if math.hypot(nx-p[0],ny-p[1])>3.5:
                            chosen=a2
                            if off:self.nav[id]=(chosen,t+2.5)
                            break
                move=[math.cos(chosen),math.sin(chosen)]
            action={'tick':engine.tick,'move':move,'aim':[gyaw,0], 'boost':me['energy']>25 and (not me['in_zone'] or dist(p,z['next_center'])>z['next_radius']*0.75),
                    'fire':[False,False]}
            if target and dist(p,target['pos'])<210:
                center=[target['pos'][0],target['pos'][1],target['pos'][2]+4.5]
                src=[p[0],p[1],p[2]+me['stats']['muzzle_height']]
                predicted=lead(src,center,target['vel'],me['weapons'][0]['stats']['speed'])
                f=k['lead_fraction'][d];pt=[center[i]+(predicted[i]-center[i])*f for i in range(3)]
                noise=math.radians(k['aim_noise_deg'][d]);yaw=math.atan2(pt[1]-p[1],pt[0]-p[0])+self.rng.gauss(0,noise)
                pitch=math.atan2(pt[2]-src[2],max(1,dist(p,pt)))+self.rng.gauss(0,noise*0.5)
                action['aim']=[yaw,pitch];action['fire']=[True,True]
            near=[q for q in obs['pickups'] if q['kind']!='gun' and dist(q['pos'],p)<engine.c['loot']['pickup_radius']]
            if near and me['weapons'][1] is None:action['take']=near[0]['id']
            if obs['offer']:action['pick']=self.rng.randrange(len(obs['offer']['choices']))
            if me['weapons'][0] and me['weapons'][0]['ammo']<3:action['reload']=True
            self.last_action[id]={key:val for key,val in action.items() if key!='tick'}
            actions[id]=action
        return actions
