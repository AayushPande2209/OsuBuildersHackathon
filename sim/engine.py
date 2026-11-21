"""Deterministic, headless approximation of mechfight/1. One step is 0.05 s."""
from __future__ import annotations
import copy
import math
import random
from collections import defaultdict
from protocol import CONFIG, KIT, validate
from world import World

DT = 0.05
TAU = 2*math.pi

def wrap(a): return (a+math.pi)%TAU-math.pi
def dist(a,b): return math.hypot(a[0]-b[0],a[1]-b[1])
def clamp(x,lo,hi): return max(lo,min(hi,x))
def interp(a,b,t): return a+(b-a)*t

def placement(dead, survivors):
    """Same-tick dead share the number alive immediately before their deaths."""
    return {m['id']:survivors for m in dead}


def lead(src, target, velocity, speed):
    rx,ry=target[0]-src[0],target[1]-src[1]
    a=velocity[0]**2+velocity[1]**2-speed**2
    b=2*(rx*velocity[0]+ry*velocity[1]); c=rx*rx+ry*ry
    disc=b*b-4*a*c
    if disc>=0 and abs(a)>1e-9:
        roots=[t for t in ((-b-math.sqrt(disc))/(2*a),(-b+math.sqrt(disc))/(2*a)) if t>0]
        t=min(roots) if roots else math.sqrt(c)/speed
    else: t=math.sqrt(c)/speed
    return [target[0]+velocity[0]*t,target[1]+velocity[1]*t,target[2]]


def mortar_pitch(horizontal, dz, speed, gravity):
    v2=speed*speed; disc=v2*v2-gravity*(gravity*horizontal*horizontal+2*dz*v2)
    if disc<0: return None
    return math.atan2(v2-math.sqrt(disc),gravity*horizontal)


class Engine:
    def __init__(self,seed=1,slot=0,map_dir=None,config=None,validate_messages=True):
        self.rng=random.Random(seed); self.seed=seed; self.slot=slot
        self.c=copy.deepcopy(config or CONFIG)
        self.map_dir=str(map_dir or KIT/'arena'); self.world=World(self.map_dir)
        self.validate_messages=validate_messages
        self.tick=0; self.next_id=30000
        self.me=[]; self.npcs=[]; self.crates=[]; self.cubes=[]; self.pickups=[]; self.projectiles=[]; self.drops=[]
        self.events=defaultdict(list); self.sounds=[]; self.beams=[]; self.memory=defaultdict(dict)
        self.deaths=[]; self.kills=defaultdict(int); self.death_info={}
        self.zone_centers=self._zone_centers()
        self._spawn()

    @property
    def t(self): return self.tick*DT
    def _id(self):
        self.next_id+=1;return self.next_id
    def _zone_centers(self):
        z=self.c['zone']; centers=[z['start_center']]
        for p in z['phases']:
            prev=centers[-1]; radius=p['radius']; old=z['start_radius'] if len(centers)==1 else z['phases'][len(centers)-2]['radius']
            slack=max(0,old-radius); theta=self.rng.uniform(-math.pi,math.pi); d=slack*self.rng.uniform(0,0.75)
            centers.append([prev[0]+d*math.cos(theta),prev[1]+d*math.sin(theta)])
        return centers
    def zone(self):
        z=self.c['zone']; elapsed=0; last_radius=z['start_radius']
        for i,p in enumerate(z['phases']):
            start=elapsed+p['hold_s']; end=start+p['shrink_s']; current=self.zone_centers[i]; nxt=self.zone_centers[i+1]
            if self.t<end or i==len(z['phases'])-1:
                f=clamp((self.t-start)/max(0.001,p['shrink_s']),0,1)
                return {'center':[interp(current[j],nxt[j],f) for j in (0,1)],'radius':interp(last_radius,p['radius'],f),
                        'next_center':nxt,'next_radius':p['radius'],'shrink_start':start,'shrink_end':end,'dps':p['dps']}
            elapsed=end;last_radius=p['radius']
        raise AssertionError
    def _point(self,center=None,radius=430,roof=False):
        center=center or self.zone_centers[0]
        for _ in range(4000):
            a=self.rng.uniform(-math.pi,math.pi);r=radius*math.sqrt(self.rng.random());x=center[0]+r*math.cos(a);y=center[1]+r*math.sin(a)
            if self.world.open_spawn(x,y):
                z=self.world.floor(x,y,None) if roof else self.world.terrain(x,y)
                if not self.world.solid(x,y,z+1): return [x,y,z]
        raise RuntimeError('could not find spawn')
    def _weapon(self,kind):
        return {'kind':kind,'cooldown':0.0,'ammo':self.c['weapons']['gun']['mag'] if kind=='gun' else None,'reload':0.0,'charge':0.0,'short':0.0}
    def _spawn(self):
        mc=self.c['mech']; match=self.c['match']; pts=[]
        for i in range(int(match['mechs'])):
            for attempt in range(20000):
                pos=self._point(radius=self.c['zone']['start_radius']*match['spawn_zone_fraction'])
                if all(dist(pos,p)>=match['spawn_min_separation'] for p in pts): break
            else: raise RuntimeError('spawn packing failed')
            pts.append(pos)
            self.me.append({'id':i,'pos':pos,'vel':[0.,0.,0.],'aim':[self.rng.uniform(-math.pi,math.pi),0.],
                'command_aim':[0.,0.],'hp':mc['hp'],'energy':mc['energy'],'grounded':True,'cubes':0,'upgrades':[],
                'weapons':[self._weapon('gun'),None],'alive':True,'action':{},'last_good':{},'miss_since':None,
                'last_hurt':-99.,'last_spent':-99.,'last_dealt':-99.,'offer':None,'offer_queue':0,'offered':0,'mem':{},'step_at':0.})
        for i in range(int(self.c['npc']['count'])):
            p=self._point();self.npcs.append({'id':100+i,'kind':'npc','pos':p,'home':p[:],'vel':[0.,0.,0.],
                'aim':[0.,0.],'hp':self.c['npc']['hp'],'max_hp':self.c['npc']['hp'],'cooldown':self.rng.random(),'target':None})
        for i in range(int(self.c['crates']['count'])):
            p=self._point(roof=self.rng.random()<self.c['crates']['roof_fraction'])
            self.crates.append({'id':1000+i,'pos':p,'hp':self.c['crates']['hp']})
        kinds=['mortar','laser','lightning']
        for i in range(int(self.c['loot']['floor_count'])):
            p=self._point(roof=self.rng.random()<self.c['loot']['floor_roof_fraction'])
            self.pickups.append({'id':8000+i,'kind':self.rng.choice(kinds),'pos':p})

    def stats(self,m):
        stamp=(m['cubes'],tuple(m['upgrades']))
        if m.get('_stats_stamp')==stamp:return m['_stats_cache']
        base=self.c['mech'].copy(); wc={k:v.copy() for k,v in self.c['weapons'].items()}
        for uid in m['upgrades']:
            up=next((u for u in self.c['upgrades'] if u['id']==uid),None)
            if not up: continue
            for ef in up['effects']:
                path=ef['path'].split('.')
                if path[0]=='mech': d=base; key=path[1]
                elif path[0]=='weapons': d=wc[path[1]];key=path[2]
                else:continue
                d[key]=d[key]*ef.get('mul',1)+ef.get('add',0)
        scale=1+min(m['cubes'],self.c['cubes']['stat_cap'])*self.c['cubes']['hp_per_cube']
        base['hp']*=scale
        size=1+m['cubes']*self.c['cubes']['size_per_cube']
        for key in ('radius','height','eye_height','muzzle_height'):base[key]*=size
        m['_stats_stamp']=stamp;m['_stats_cache']=(base,wc)
        return base,wc
    def _maxhp(self,m):return self.stats(m)[0]['hp']
    def hello(self):
        h={'type':'hello','protocol':'mechfight/1','slot':self.slot,'seed':self.rng.getrandbits(32),
           'map':{'dir':self.map_dir,'files':['v2/world.json','v2/terrain.i16']},'config':self.c}
        return validate('Hello',h) if self.validate_messages else h
    def _visible(self,viewer,pos):
        st,_=self.stats(viewer); src=[viewer['pos'][0],viewer['pos'][1],viewer['pos'][2]+st['eye_height']]
        d=dist(viewer['pos'],pos)
        if d>self.c['vision']['range']+st['vision_bonus'] and d>self.c['vision']['near_range']+st['near_range_bonus']:return False
        if d>self.c['vision']['near_range']+st['near_range_bonus']:
            a=math.atan2(pos[1]-src[1],pos[0]-src[0])
            if abs(wrap(a-viewer['aim'][0]))>math.radians(self.c['vision']['fov_deg']/2):return False
        return not self.world.line_block(src,[pos[0],pos[1],pos[2]+2])
    def house_observation(self,id):
        """Internal reduced observation; same visibility rule, only fields house AI reads."""
        m=self.me[id]; st,wstats=self.stats(m);p=m['pos'];z=self.zone()
        actors=[]
        for other in self.me+self.npcs:
            if other['id']==id or other.get('hp',0)<=0 or ('alive' in other and not other['alive']):continue
            if self._visible(m,other['pos']):
                actors.append({'id':other['id'],'kind':other.get('kind','mech'),'pos':other['pos'][:],
                               'vel':other['vel'][:], 'aim':other['aim'][:]})
        pickups=[{'id':q['id'],'kind':q['kind'],'pos':q['pos'][:]} for q in self.pickups if self._visible(m,q['pos'])]
        weapons=[]
        for w in m['weapons']:
            weapons.append(None if w is None else {'kind':w['kind'],'ammo':w['ammo'],'stats':wstats[w['kind']]})
        return {'self':{'pos':p[:],'weapons':weapons,'energy':m['energy'],'in_zone':dist(p,z['center'])<=z['radius'],
                        'stats':st},'mechs':actors,'pickups':pickups,'zone':z,'offer':m['offer']}

    def observation(self,id):
        m=self.me[id]; st,wstats=self.stats(m); z=self.zone(); p=m['pos']; t=self.t
        actors=[]
        for other in self.me+self.npcs:
            if other['id']==id or (other.get('kind')!='npc' and not other['alive']) or other.get('hp',0)<=0:continue
            q=other['pos']; seen=self._visible(m,q)
            if seen:m['mem'][other['id']]=t
            elif t-m['mem'].get(other['id'],-99)>self.c['vision']['memory_s']:continue
            item={'id':other['id'],'kind':other.get('kind','mech'),'pos':q[:],'vel':other['vel'][:], 'aim':other['aim'][:]}
            if self.c['vision']['show_enemy_hp']:
                item.update(hp=other['hp'],max_hp=self._maxhp(other) if item['kind']=='mech' else other['max_hp'])
            if item['kind']=='mech':
                item.update(cubes=other['cubes'],weapons=[w['kind'] for w in other['weapons'] if w],charging=any(w and w['kind']=='laser' and w['charge']>0 for w in other['weapons']))
            actors.append(item)
        def seen_items(items,make):return [make(q) for q in items if self._visible(m,q['pos'])]
        projs=seen_items([q for q in self.projectiles if q['owner']!=id],lambda q:{k:q[k] for k in ('id','kind','pos','vel')})
        crates=seen_items(self.crates,lambda q:{k:q[k] for k in ('id','pos','hp')})
        cubes=seen_items(self.cubes,lambda q:{k:q[k] for k in ('id','pos')})
        pickups=seen_items(self.pickups,lambda q:{k:q[k] for k in ('id','kind','pos')})
        heard=[]
        for s in self.sounds:
            if s['by']==id:continue
            dd=dist(p,s['pos']); rng=self.c['sound']['range'].get(s['kind'],0)
            if dd>rng or t-s['t']>0.3:continue
            a=math.atan2(s['pos'][1]-p[1],s['pos'][0]-p[0]); sigma=math.radians(self.c['sound']['bearing_noise_deg'])*st['hearing']
            heard.append({'kind':s['kind'],'bearing':wrap(a+self.rng.gauss(0,sigma)),
                          'dist':'near' if dd<self.c['sound']['near'] else 'mid' if dd<self.c['sound']['mid'] else 'far','age':max(0,t-s['t'])})
        beams=[{'by':b['by'],'kind':b['kind'],'path':b['path'],'age':t-b['t']} for b in self.beams if b['by']!=id and t-b['t']<=0.15 and any(self._visible(m,pt) for pt in b['path'])]
        weapons=[]
        for w in m['weapons']:
            if w is None:weapons.append(None);continue
            item={'kind':w['kind'],'cooldown':max(0,w['cooldown']),'stats':wstats[w['kind']]}
            if w['kind']=='gun':item.update(ammo=w['ammo'],reload=max(0,w['reload']))
            if w['kind']=='laser':item['charge']=w['charge']
            weapons.append(item)
        selfobs={'id':id,'pos':p[:],'vel':m['vel'][:],'aim':m['aim'][:],'hp':m['hp'],'max_hp':st['hp'],
                 'energy':m['energy'],'max_energy':st['energy'],'grounded':m['grounded'],'cubes':m['cubes'],
                 'upgrades':m['upgrades'][:],'weapons':weapons,'in_zone':dist(p,z['center'])<=z['radius'],'stats':st}
        drops=[{'id':d['id'],'pos':d['pos'][:],'radius':d['radius'],'lands_in':max(0,d['land']-t),
                'capture_s':d['capture_s'],'progress':d['progress'],'holder':d['holder']} for d in self.drops]
        obs={'type':'obs','tick':self.tick,'t':t,'alive':sum(q['alive'] for q in self.me),'self':selfobs,
             'mechs':actors,'projectiles':projs,'crates':crates,'cubes':cubes,'pickups':pickups,'sounds':heard,
             'beams':beams,'events':self.events[id][:],'zone':z,'offer':m['offer'],'drops':drops}
        if self.validate_messages:validate('Observation',obs)
        return obs
    def sound(self,kind,source,by):self.sounds.append({'kind':kind,'pos':source[:],'by':by,'t':self.t})
    def _damage(self,target,amount,weapon,by,source):
        if target.get('hp',0)<=0 or (by is not None and by<16 and by!=self.slot and target.get('id',-1)<16 and target['id']!=self.slot):return
        if target.get('kind')!='npc' and 'alive' in target:
            st,_=self.stats(target)
            if weapon=='zone':
                yaw=None;rear=False
            else:
                amount*=1-st['armor']
                yaw=math.atan2(source[1]-target['pos'][1],source[0]-target['pos'][0]); rear=abs(wrap(yaw-target['aim'][0]))>math.radians(st['front_arc_deg']/2)
                if rear:amount*=st['rear_mult']
            target['last_hurt']=self.t
            self.events[target['id']].append({'type':'damaged','amount':amount,'weapon':weapon,'bearing':yaw,'by':by,'rear':rear})
        else:rear=False
        target['hp']-=amount
        if by is not None and by<16 and by!=target['id']:
            self.me[by]['last_dealt']=self.t
            self.events[by].append({'type':'hit','target':target['id'],'amount':amount,'weapon':weapon,'rear':rear})
        if target['hp']<=0 and target.get('kind')=='npc':
            self._drop_cubes(target['pos'],self.c['npc']['cubes'])
            self.npcs.remove(target)
        if target['hp']<=0 and target in self.crates:
            self._drop_cubes(target['pos'],self.c['crates']['cubes']);self.crates.remove(target)
            if self.rng.random()<self.c['loot']['crate_weapon_chance']:
                self.pickups.append({'id':self._id(),'kind':self.rng.choice(['mortar','laser','lightning']),'pos':target['pos'][:]})
    def _drop_cubes(self,pos,n):
        for _ in range(int(n)):
            self.cubes.append({'id':self._id(),'pos':[pos[0]+self.rng.uniform(-2,2),pos[1]+self.rng.uniform(-2,2),pos[2]]})
    def _offers(self,m):
        thresholds=self.c['cubes']['upgrade_thresholds']
        n=sum(m['cubes']>=q for q in thresholds)
        if n>m['offered']:m['offer_queue']+=n-m['offered'];m['offered']=n
        if m['offer'] is None and m['offer_queue']:
            have=[w['kind'] for w in m['weapons'] if w];choices=[]
            for u in self.c['upgrades']:
                if u.get('requires') and u['requires'] not in have:continue
                if m['upgrades'].count(u['id'])>=u['max']:continue
                choices.append(u)
            if choices:
                picks=self.rng.sample(choices,min(3,len(choices)))
                m['offer']={'id':m['offered']-m['offer_queue']+1,'expires':self.t+self.c['bot']['offer_timeout_s'],
                            'choices':[{k:u[k] for k in ('id','name','desc')} for u in picks]}
            m['offer_queue']-=1
    def _pick(self,m,index):
        if m['offer'] is None:return
        opts=m['offer']['choices'];idx=int(index) if isinstance(index,(float,int)) else 0
        idx=idx if 0<=idx<len(opts) else 0; uid=opts[idx]['id']; oldhp=self._maxhp(m)
        m['upgrades'].append(uid);m['offer']=None
        m['hp']+=self._maxhp(m)-oldhp
        self.events[m['id']].append({'type':'upgrade','id':uid})
    def actions(self,actions):
        # Called once per 2 ticks. Reset per-observation events after clients have read them.
        self.events=defaultdict(list)
        for m in self.me:
            if not m['alive']:continue
            raw=actions.get(m['id'])
            if raw is not None:
                if self.validate_messages:validate('Action',raw)
                if raw.get('tick')!=self.tick:raw=None
            if raw is None:
                if m['miss_since'] is None:m['miss_since']=self.t
                if self.t-m['miss_since']>self.c['bot']['coast_s'] or m.get('crashed'):
                    raw={'tick':self.tick}
                else:raw={'tick':self.tick,**{k:v for k,v in m['last_good'].items() if k in ('move','boost','aim')}}
            else:
                m['miss_since']=None;m['last_good']=raw
            m['action']=raw
            if m['offer']:
                if 'pick' in raw:self._pick(m,raw['pick'])
                elif self.t>=m['offer']['expires']:self._pick(m,0)
            if 'aim' in raw:m['command_aim']=raw['aim'][:]
            if raw.get('reload'):
                for w in m['weapons']:
                    if w and w['kind']=='gun' and w['reload']<=0 and w['ammo']<self.stats(m)[1]['gun']['mag']:
                        w['reload']=self.stats(m)[1]['gun']['reload'];self.sound('reload',m['pos'],m['id'])
        # Simultaneous take conflicts: closest wins.
        wants=defaultdict(list)
        for m in self.me:
            if m['alive'] and 'take' in m['action']:wants[m['action']['take']].append(m)
        for pid,who in wants.items():
            item=next((p for p in self.pickups if p['id']==pid),None)
            if not item:
                for m in who:self.events[m['id']].append({'type':'take_failed','id':pid,'reason':'gone'})
                continue
            winner=min(who,key=lambda m:(dist(m['pos'],item['pos']),m['id']))
            for m in who:
                if m is not winner:self.events[m['id']].append({'type':'take_failed','id':pid,'reason':'gone'})
            m=winner;reason=None
            if dist(m['pos'],item['pos'])>self.c['loot']['pickup_radius'] or abs(m['pos'][2]-item['pos'][2])>4:reason='range'
            elif any(w and w['kind']==item['kind'] for w in m['weapons']):reason='have'
            else:
                slot=next((i for i,w in enumerate(m['weapons']) if w is None),None)
                if slot is None:slot=m['action'].get('drop');reason='full' if slot not in (0,1) else None
                if reason is None and m['weapons'][slot] and m['weapons'][slot]['kind']=='laser' and m['weapons'][slot]['charge']>0:reason='busy'
            if reason:self.events[m['id']].append({'type':'take_failed','id':pid,'reason':reason});continue
            old=m['weapons'][slot];m['weapons'][slot]=self._weapon(item['kind']);m['weapons'][slot]['cooldown']=self.c['loot']['equip_s']
            self.pickups.remove(item);self.events[m['id']].append({'type':'took','id':pid,'kind':item['kind'],'slot':slot})
            if old:
                dropped={'id':self._id(),'kind':old['kind'],'pos':m['pos'][:]};self.pickups.append(dropped)
                self.events[m['id']].append({'type':'dropped','id':dropped['id'],'kind':old['kind'],'slot':slot})
        for m in self.me:
            if not m['alive'] or 'take' in m['action']:continue
            slot=m['action'].get('drop')
            if slot in (0,1) and m['weapons'][slot]:
                old=m['weapons'][slot]
                if old['kind']=='laser' and old['charge']>0:continue
                m['weapons'][slot]=None;item={'id':self._id(),'kind':old['kind'],'pos':m['pos'][:]};self.pickups.append(item)
                self.events[m['id']].append({'type':'dropped','id':item['id'],'kind':old['kind'],'slot':slot})
    def _ray_target(self,source,direction,length,owner,radius=0):
        best=None;bestt=length
        for q in self.me+self.npcs+self.crates:
            if q['id']==owner or (owner is not None and owner<16 and owner!=self.slot and q.get('id',-1)<16 and q['id']!=self.slot) or q.get('hp',0)<=0 or ('alive' in q and not q['alive']):continue
            center=[q['pos'][0],q['pos'][1],q['pos'][2]+(4.5 if 'alive' in q else 1.5)]
            vx,vy,vz=[center[i]-source[i] for i in range(3)]
            t=vx*direction[0]+vy*direction[1]+vz*direction[2]
            if not 0<t<bestt:continue
            closest=[source[i]+t*direction[i] for i in range(3)]
            rr=(self.stats(q)[0]['radius'] if 'alive' in q else q.get('radius',1.8))+radius
            if math.dist(center,closest)>rr+1:continue
            if self.world.line_block(source,closest):continue
            best,bestt=q,t
        return best,bestt
    def _shoot(self,m,w,st,wst,slot):
        kind=w['kind']; cfg=wst[kind];a,p=m['aim']; source=[m['pos'][0],m['pos'][1],m['pos'][2]+(st['muzzle_height'] if kind!='mortar' else st['height']+0.5)]
        damage_scale=1+self.c['cubes']['damage_per_cube']*min(m['cubes'],self.c['cubes']['stat_cap'])
        if kind in ('gun','mortar'):
            if kind=='gun':
                if w['ammo']<=0:
                    w['reload']=cfg['reload'];return
                w['ammo']-=1;p+=self.rng.gauss(0,math.radians(cfg['spread_deg']));a+=self.rng.gauss(0,math.radians(cfg['spread_deg']))
            direction=[math.cos(p)*math.cos(a),math.cos(p)*math.sin(a),math.sin(p)]
            pos=[source[i]+direction[i]*min(3,st['radius']+0.5) for i in range(3)]
            if self.world.line_block(source,pos):pos=source[:]
            self.projectiles.append({'id':self._id(),'kind':kind,'pos':pos,'vel':[cfg['speed']*q for q in direction],
                                     'owner':m['id'],'range':cfg.get('range',cfg.get('speed',72)*cfg.get('ttl',7)),
                                     'traveled':0.,'damage_scale':damage_scale})
            w['cooldown']=cfg['cooldown'];self.sound(kind,m['pos'],m['id'])
        elif kind=='laser':
            charge=max(w['charge'],cfg['min_charge']);fraction=clamp(charge/cfg['charge'],0,1)
            direction=[math.cos(p)*math.cos(a),math.cos(p)*math.sin(a),math.sin(p)]
            dst=[source[i]+direction[i]*cfg['range'] for i in range(3)]
            hit,t=self._ray_target(source,direction,cfg['range'],m['id'])
            if hit:
                damage=cfg['damage']*(cfg['min_frac']+(1-cfg['min_frac'])*fraction)*damage_scale
                if 'alive' in hit and any(q and q['kind']=='mortar' for q in hit['weapons']):damage*=1+cfg['cookoff']
                self._damage(hit,damage,'laser',m['id'],source);dst=[source[i]+direction[i]*t for i in range(3)]
            self.beams.append({'by':m['id'],'kind':'laser','path':[source,dst],'t':self.t})
            self.sound('laser',m['pos'],m['id']);w['charge']=0;w['cooldown']=cfg['cooldown']
        elif kind=='lightning':
            if m['energy']<cfg['energy']:return
            m['energy']-=cfg['energy'];m['last_spent']=self.t;w['cooldown']=cfg['cooldown']
            eligible=[]
            for q in self.me+self.npcs+self.crates:
                if q['id']==m['id'] or q.get('hp',0)<=0 or ('alive' in q and not q['alive']):continue
                d=dist(q['pos'],m['pos']); yaw=math.atan2(q['pos'][1]-m['pos'][1],q['pos'][0]-m['pos'][0])
                if d<=cfg['range'] and abs(wrap(yaw-a))<=math.radians(cfg['cone_deg']/2) and not self.world.line_block(source,[q['pos'][0],q['pos'][1],q['pos'][2]+2]):eligible.append((d,q))
            path=[source];used=set();target=min(eligible,key=lambda x:x[0])[1] if eligible else None
            for chain in range(int(cfg['chain'])+1):
                if target is None:break
                self._damage(target,cfg['damage']*damage_scale*(cfg['chain_falloff']**chain),'lightning',m['id'],path[-1])
                if 'alive' in target:
                    for ww in target['weapons']:
                        if ww and ww['kind']=='laser':ww['charge']=0;ww['short']=cfg['short_s']
                used.add(target['id']);path.append([target['pos'][0],target['pos'][1],target['pos'][2]+2])
                options=[q for q in self.me+self.npcs+self.crates if q['id'] not in used and q['id']!=m['id'] and q.get('hp',0)>0 and dist(q['pos'],target['pos'])<=cfg['chain_range']]
                target=min(options,key=lambda q:dist(q['pos'],path[-1])) if options else None
            if len(path)==1:path.append([source[0]+cfg['range']*math.cos(a),source[1]+cfg['range']*math.sin(a),source[2]])
            self.beams.append({'by':m['id'],'kind':'lightning','path':path,'t':self.t});self.sound('lightning',m['pos'],m['id'])
    def _explosion(self,pos,p,owner):
        cfg=self.c['weapons']['mortar'];self.sound('explosion',pos,owner)
        direct,t=self._ray_target(p['old'],[(pos[i]-p['old'][i])/max(0.001,math.dist(pos,p['old'])) for i in range(3)],math.dist(pos,p['old'])+1,owner,0.5)
        if direct:self._damage(direct,cfg['damage']*p['damage_scale'],'mortar',owner,pos)
        for q in list(self.me+self.npcs+self.crates):
            if q.get('hp',0)<=0 or ('alive' in q and not q['alive']):continue
            d=math.dist(pos,[q['pos'][0],q['pos'][1],q['pos'][2]+2])
            if d>cfg['splash_radius'] or self.world.line_block(pos,[q['pos'][0],q['pos'][1],q['pos'][2]+2]):continue
            fall=1-(1-cfg['splash_edge'])*d/cfg['splash_radius'];scale=self.c['mech']['self_damage_mult'] if q['id']==owner else 1
            self._damage(q,cfg['splash']*fall*scale*p['damage_scale'],'mortar',owner,pos)
            if 'alive' in q:
                dd=max(0.1,dist(q['pos'],pos));q['vel'][0]+=(q['pos'][0]-pos[0])/dd*cfg['knock']*fall
                q['vel'][1]+=(q['pos'][1]-pos[1])/dd*cfg['knock']*fall;q['vel'][2]+=cfg['knock_up']*fall
                q['energy']=max(0,q['energy']-cfg['drain']*fall)
    def _projectiles(self):
        for p in self.projectiles[:]:
            p['old']=p['pos'][:];p['pos']=[p['pos'][i]+p['vel'][i]*DT for i in range(3)]
            if p['kind']=='mortar':p['vel'][2]-=self.c['weapons']['mortar']['gravity']*DT
            seg=math.dist(p['old'],p['pos']);p['traveled']+=seg
            if p['traveled']>p['range']:
                self.projectiles.remove(p);continue
            blocked=self.world.line_block(p['old'],p['pos']) or p['pos'][2]<=self.world.terrain(*p['pos'][:2])
            vec=[(p['pos'][i]-p['old'][i])/max(seg,1e-6) for i in range(3)]
            hit,t=self._ray_target(p['old'],vec,seg,p['owner'],self.c['projectile'].get('gun_radius',0.3))
            if hit or blocked:
                if p['kind']=='mortar':self._explosion(p['pos'],p,p['owner'])
                elif hit:self._damage(hit,(self.c['weapons']['gun']['damage'] if p['kind']=='gun' else self.c['npc']['damage'])*p['damage_scale'],p['kind'],p['owner'],p['old'])
                self.projectiles.remove(p)
    def _move(self,m):
        st,wstats=self.stats(m);a=m['action'];mx,my=(a.get('move') or [0,0])[:2];mag=math.hypot(mx,my)
        if mag>1:mx/=mag;my/=mag
        if any(w and w['kind']=='laser' and w['charge']>0 for w in m['weapons']):charge_mult=st['charge_move_mult']
        else:charge_mult=1
        boosting=bool(a.get('boost') and m['energy']>0)
        speed=(st['boost_speed'] if boosting and m['grounded'] else st['walk_speed'])*charge_mult
        accel=st['ground_accel'] if m['grounded'] else st['air_accel']
        for i,des in enumerate((mx*speed,my*speed)):
            m['vel'][i]+=clamp(des-m['vel'][i],-accel*DT,accel*DT)
        if a.get('jump') and m['grounded']:
            m['vel'][2]=st['jump_speed'];m['grounded']=False
        if boosting:
            drain=st['boost_drain'] if m['grounded'] else st['jet_drain'];m['energy']=max(0,m['energy']-drain*DT);m['last_spent']=self.t
            if not m['grounded']:m['vel'][2]=min(st['max_rise_speed'],m['vel'][2]+st['jet_accel']*DT)
        elif self.t-m['last_spent']>st['energy_regen_delay']:
            m['energy']=min(st['energy'],m['energy']+st['energy_regen']*DT)
        m['vel'][2]-=st['gravity']*DT
        x,y,z=m['pos'];nx,ny=self.world.slide(x,y,z,m['vel'][0]*DT,m['vel'][1]*DT,st['radius'],st['step_up'],st['max_slope_deg'])
        if nx==x:m['vel'][0]=0
        if ny==y:m['vel'][1]=0
        nz=z+m['vel'][2]*DT;floor=self.world.floor(nx,ny,nz)
        if nz<=floor:
            nz=floor;m['vel'][2]=0;m['grounded']=True
        else:m['grounded']=False
        m['pos']=[nx,ny,nz]
        desired=m['command_aim'];m['aim'][0]=wrap(m['aim'][0]+clamp(wrap(desired[0]-m['aim'][0]),-st['turn_rate']*DT,st['turn_rate']*DT))
        pitch=clamp(desired[1],st['min_pitch'],st['max_pitch'])
        m['aim'][1]+=clamp(pitch-m['aim'][1],-st['pitch_rate']*DT,st['pitch_rate']*DT)
        if m['grounded'] and math.hypot(*m['vel'][:2])>self.c['sound']['step_speed'] and self.t>=m['step_at']:
            self.sound('boost' if boosting else 'step',m['pos'],m['id']);m['step_at']=self.t+self.c['sound']['step_every']
        if not m['grounded'] and boosting and self.tick%4==0:self.sound('jet',m['pos'],m['id'])
        zinfo=self.zone()
        if dist(m['pos'],zinfo['center'])>zinfo['radius']:
            self._damage(m,zinfo['dps']*DT,'zone',None,zinfo['center'])
        elif self.t-max(m['last_hurt'],m['last_dealt'])>st['regen_delay']:
            m['hp']=min(st['hp'],m['hp']+st['regen_per_s']*DT)
        for w in m['weapons']:
            if not w:continue
            was_reloading=w['reload']>0
            w['cooldown']=max(0,w['cooldown']-DT);w['reload']=max(0,w['reload']-DT);w['short']=max(0,w['short']-DT)
            if w['kind']=='gun' and was_reloading and w['reload']==0:w['ammo']=wstats['gun']['mag']
        for slot,w in enumerate(m['weapons']):
            if not w:continue
            hold=bool((a.get('fire') or [False,False])[slot])
            if w['kind']=='laser':
                if hold and w['cooldown']==0 and w['short']==0:
                    if w['charge']==0:self.sound('laser_charge',m['pos'],m['id'])
                    w['charge']+=DT
                    if w['charge']>=wstats['laser']['charge']+wstats['laser']['hold_s']:self._shoot(m,w,st,wstats,slot)
                elif not hold and w['charge']>0 and w['cooldown']==0:
                    if w['charge']>=wstats['laser']['min_charge']:self._shoot(m,w,st,wstats,slot)
                    else:w['charge']=wstats['laser']['min_charge'];self._shoot(m,w,st,wstats,slot)
            elif hold and w['cooldown']==0 and w['reload']==0:self._shoot(m,w,st,wstats,slot)
    def _npcs(self):
        c=self.c['npc']
        for n in self.npcs[:]:
            n['cooldown']=max(0,n['cooldown']-DT)
            possible=[m for m in self.me if m['alive'] and dist(m['pos'],n['pos'])<c['aggro_range'] and not self.world.line_block([n['pos'][0],n['pos'][1],n['pos'][2]+2],[m['pos'][0],m['pos'][1],m['pos'][2]+4])]
            target=min(possible,key=lambda m:dist(m['pos'],n['pos'])) if possible and dist(n['pos'],n['home'])<c['chase_leash'] else None
            goal=target['pos'] if target else n['home']
            dd=dist(n['pos'],goal)
            if dd>2:
                dx=(goal[0]-n['pos'][0])/dd*c['speed']*DT;dy=(goal[1]-n['pos'][1])/dd*c['speed']*DT
                x,y=self.world.slide(n['pos'][0],n['pos'][1],n['pos'][2],dx,dy,c['radius']);n['pos']=[x,y,self.world.terrain(x,y)]
                n['vel']=[dx/DT,dy/DT,0]
            if target and n['cooldown']==0:
                a=math.atan2(target['pos'][1]-n['pos'][1],target['pos'][0]-n['pos'][0])+self.rng.gauss(0,math.radians(c['spread_deg']))
                n['aim']=[a,0];source=[n['pos'][0],n['pos'][1],n['pos'][2]+2]
                self.projectiles.append({'id':self._id(),'kind':'npc','pos':source,'vel':[math.cos(a)*c['projectile_speed'],math.sin(a)*c['projectile_speed'],0],
                                         'owner':n['id'],'range':c['aggro_range']*2,'traveled':0,'damage_scale':1})
                self.sound('npc_gun',n['pos'],n['id']);n['cooldown']=c['cooldown']
    def _loot(self):
        for cube in self.cubes[:]:
            candidates=[m for m in self.me if m['alive'] and dist(m['pos'],cube['pos'])<self.c['cubes']['pickup_radius'] and abs(m['pos'][2]-cube['pos'][2])<4]
            if candidates:
                m=min(candidates,key=lambda q:(dist(q['pos'],cube['pos']),q['id']));old=self._maxhp(m);m['cubes']+=1
                m['hp']+=self._maxhp(m)-old;self.cubes.remove(cube)
                self.events[m['id']].append({'type':'pickup','cubes':m['cubes']});self._offers(m)
    def _drops(self):
        c=self.c['drops']
        for i,call in enumerate(c['times']):
            if self.tick==int(call/DT):
                z=self.zone();pos=self._point(center=z['next_center'],radius=max(5,z['next_radius']*c['spread']))
                self.drops.append({'id':20000+i,'pos':pos,'radius':c['radius'],'land':self.t+c['fall_s'],'capture_s':c['capture_s'],'holder':None,'progress':0})
        for d in self.drops[:]:
            if self.t<d['land']:continue
            inside=[m for m in self.me if m['alive'] and dist(m['pos'],d['pos'])<d['radius']]
            if len(inside)==1:
                m=inside[0]
                if d['holder']!=m['id']:d['holder']=m['id'];d['progress']=0
                d['progress']+=DT
                if d['progress']>=d['capture_s']:
                    old=self._maxhp(m);m['cubes']+=c['cubes'];m['hp']=self._maxhp(m) if c['repair'] else m['hp']+self._maxhp(m)-old
                    m['energy']=self.stats(m)[0]['energy'];self._offers(m)
                    self.events[m['id']].append({'type':'drop','id':d['id'],'cubes':m['cubes']});self.drops.remove(d)
            elif not inside:d['holder']=None;d['progress']=0
    def _push(self):
        live=[m for m in self.me if m['alive']]
        for i,a in enumerate(live):
            for b in live[i+1:]:
                d=dist(a['pos'],b['pos']);r=self.stats(a)[0]['radius']+self.stats(b)[0]['radius']
                if 0<d<r and abs(a['pos'][2]-b['pos'][2])<7:
                    shift=(r-d)/2;dx=(a['pos'][0]-b['pos'][0])/d*shift;dy=(a['pos'][1]-b['pos'][1])/d*shift
                    a['pos'][0]+=dx;a['pos'][1]+=dy;b['pos'][0]-=dx;b['pos'][1]-=dy
    def _deaths(self):
        dead=[m for m in self.me if m['alive'] and m['hp']<=0]
        places=placement(dead,sum(m['alive'] for m in self.me))
        for m in dead:
            m['alive']=False;info=next((e for e in reversed(self.events[m['id']]) if e['type']=='damaged'),{})
            self.death_info[m['id']]={'place':places[m['id']],'time':self.t,'killer':info.get('by'),'weapon':info.get('weapon')}
            self.deaths.append(m['id']);self.sound('death',m['pos'],m['id'])
            by=info.get('by')
            if by is not None and by<16 and by!=m['id']:
                self.kills[by]+=1;self.events[by].append({'type':'kill','target':m['id']})
            self._drop_cubes(m['pos'],m['cubes']+self.c['cubes']['death_drop_extra'])
            for w in m['weapons']:
                if w and w['kind']!='gun':self.pickups.append({'id':self._id(),'kind':w['kind'],'pos':m['pos'][:]})
    def step(self):
        for m in self.me:
            if m['alive']:self._move(m)
        self._push();self._npcs();self._projectiles();self._loot();self._drops();self._deaths()
        self.sounds=[s for s in self.sounds if self.t-s['t']<0.3]
        self.beams=[b for b in self.beams if self.t-b['t']<0.2]
        self.tick+=1
    def done(self):return sum(m['alive'] for m in self.me)<=1 or self.t>=self.c['match']['duration_s']
    def finish(self):
        survivors=sorted((m for m in self.me if m['alive']),key=lambda m:(-m['hp'],m['id']))
        rank=0; last_hp=None
        for i,m in enumerate(survivors):
            if last_hp is None or m['hp']!=last_hp:rank=i+1
            last_hp=m['hp']
            self.death_info[m['id']]={'place':rank,'time':self.t,'killer':None,'weapon':None}
        return self.death_info[self.slot]
