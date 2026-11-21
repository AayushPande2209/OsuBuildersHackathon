import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import gzip
import math
import unittest
from engine import Engine, lead, mortar_pitch, placement
from protocol import CONFIG, KIT, validate
from world import World

class Rules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.e=Engine(seed=7,validate_messages=True)
    def test_schema(self):
        validate('Hello',self.e.hello());validate('Observation',self.e.observation(0))
        validate('Action',{'tick':0,'move':[1,0],'fire':[True,False]})
        with self.assertRaises(ValueError):validate('Action',{'fire':[True,False]})
    def test_recorded_stream_schema(self):
        count=0
        with gzip.open(KIT/'check/stream.jsonl.gz','rt') as stream:
            for line in stream:
                msg=json.loads(line)
                validate({'hello':'Hello','obs':'Observation','end':'EndMsg'}[msg['type']],msg)
                count+=1
        self.assertEqual(count,302)
    def test_leading_gun(self):
        src=[0,0,0];target=[100,0,0];velocity=[0,10,0];speed=100
        aim=lead(src,target,velocity,speed)
        self.assertGreater(aim[1],10)
        t=math.dist(src,aim)/speed
        self.assertAlmostEqual(aim[1],velocity[1]*t,places=6)
        self.assertGreater(abs(target[1]-velocity[1]*t),9)
        # A stationary aim misses a radius-2.5 target; the lead intersects it.
        miss=velocity[1]*(100/speed)
        self.assertGreater(miss,2.5)
        self.assertLess(math.hypot(aim[0]-(target[0]+velocity[0]*t),aim[1]-(target[1]+velocity[1]*t)),2.5)
    def test_mortar_ballistics(self):
        r=100;v=72;g=22;pitch=mortar_pitch(r,0,v,g)
        self.assertIsNotNone(pitch)
        tof=r/(v*math.cos(pitch))
        self.assertAlmostEqual(v*math.sin(pitch)*tof-g*tof*tof/2,0,places=5)
    def test_laser_charge_release(self):
        e=Engine(3,validate_messages=False);m=e.me[0];m['weapons'][1]=e._weapon('laser')
        w=m['weapons'][1];w['charge']=e.c['weapons']['laser']['charge'];m['action']={'fire':[False,False]}
        e._move(m);self.assertEqual(w['charge'],0);self.assertGreater(w['cooldown'],0)
        self.assertTrue(any(b['kind']=='laser' for b in e.beams))
    def test_early_reload_refills(self):
        e=Engine(11,validate_messages=False);m=e.me[0];w=m['weapons'][0]
        w['ammo']=3;w['reload']=0.05;m['action']={}
        e._move(m)
        self.assertEqual(w['ammo'],CONFIG['weapons']['gun']['mag'])
    def test_zone_interpolation(self):
        e=Engine(4,validate_messages=False);e.tick=80*20;z=e.zone()
        self.assertAlmostEqual(z['radius'],560+(380-560)*(20/50))
        self.assertAlmostEqual(z['center'][0],e.zone_centers[0][0]+(e.zone_centers[1][0]-e.zone_centers[0][0])*(20/50))
    def test_wall_sliding(self):
        w=World.__new__(World)
        w.bounds={'minX':-10,'maxX':10,'minY':-10,'maxY':10}
        w.floor=lambda x,y,z:0
        w.solid=lambda x,y,z:x>=0
        nx,ny=w.slide(-3,0,0,4,2,radius=0.5)
        self.assertEqual(nx,-3)
        self.assertEqual(ny,2)
    def test_rear_armor(self):
        e=Engine(8,validate_messages=False);m=e.me[0];m['aim']=[0,0];old=m['hp']
        e._damage(m,100,'gun',1,[m['pos'][0]-10,m['pos'][1],m['pos'][2]])
        self.assertAlmostEqual(old-m['hp'],100*CONFIG['mech']['rear_mult'])
    def test_zone_ignores_armor(self):
        e=Engine(10,validate_messages=False);m=e.me[0];m['upgrades']=['armor'];m['aim']=[0,0];old=m['hp']
        e._damage(m,20,'zone',None,e.zone()['center'])
        self.assertEqual(old-m['hp'],20)
        self.assertIsNone(e.events[0][-1]['bearing'])
        self.assertFalse(e.events[0][-1]['rear'])
    def test_placement_ties(self):
        dead=[{'id':2},{'id':3}];self.assertEqual(placement(dead,8),{2:8,3:8})
    def test_determinism(self):
        cfg=json.loads(json.dumps(CONFIG));cfg['match']['duration_s']=1.0
        a,b=Engine(19,config=cfg,validate_messages=False),Engine(19,config=cfg,validate_messages=False)
        while not a.done():
            actions={i:{'tick':a.tick,'move':[0.2,0.1]} for i in range(16)}
            a.actions(actions);b.actions(actions);a.step();b.step()
        self.assertEqual([m['pos'] for m in a.me],[m['pos'] for m in b.me])
        self.assertEqual(a.finish(),b.finish())

if __name__=='__main__':unittest.main()
