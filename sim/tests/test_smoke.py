import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tempfile
import time
import unittest
from protocol import KIT
from run import run_many

class Smoke(unittest.TestCase):
    def test_two_example_matches_under_sixty_seconds(self):
        from concurrent.futures import ProcessPoolExecutor
        from run import single
        start=time.monotonic()
        with tempfile.TemporaryDirectory() as out:
            tasks=[(i,seed,0,'python3 -u kit/python/example_bot.py',str(KIT/'arena'),out,True,True,None)
                   for i,seed in enumerate((2,5))]
            with ProcessPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(single,tasks))
            self.assertEqual(len(results),2)
            self.assertTrue(all(1<=r['place']<=16 for r in results))
        self.assertLess(time.monotonic()-start,60)
if __name__=='__main__':unittest.main()
