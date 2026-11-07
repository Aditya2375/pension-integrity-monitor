"""Real subprocess termination, not only exception-based fault injection."""
import os, sys, tempfile, subprocess, pathlib, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from pim import db
ROOT=str(pathlib.Path(__file__).resolve().parents[1])
CHILD='''
import os
from pim import db
c=db.connect()
real=db._append_fsync
n=0
def interrupted(path,line):
    global n
    n+=1
    if os.environ['BOUNDARY']=='before_anchor' and n==1: os._exit(77)
    real(path,line)
    if os.environ['BOUNDARY']=='after_anchor' and n==1: os._exit(77)
    if os.environ['BOUNDARY']=='after_checkpoint' and n==2: os._exit(77)
db._append_fsync=interrupted
db.log(c,'crash-test','mutation','attempt')
c.commit()
os._exit(77)
'''
class CrashTests(unittest.TestCase):
    def test_actual_process_death(self):
        old=db.DB_PATH
        oldcp=os.environ.get('PIM_CHECKPOINT_DIR')
        try:
            for boundary, expected in [('before_anchor',True),('after_anchor',None),('after_checkpoint',None),('after_commit',True)]:
                with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as d:
                    db.DB_PATH=d+'/db.sqlite3';os.environ['PIM_CHECKPOINT_DIR']=d+'/checkpoints'
                    c=db.init_db();db.log(c,'baseline','start','');c.commit();c.close()
                    env=dict(os.environ,PIM_DB=db.DB_PATH,BOUNDARY=boundary,PYTHONPATH=ROOT)
                    proc=subprocess.run([sys.executable,'-c',CHILD],env=env,cwd=ROOT)
                    self.assertEqual(proc.returncode,77)
                    c=db.connect();self.assertIs(db.verify_audit(c)[0],expected)
                    self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='mutation'").fetchone()[0],int(boundary=='after_commit'))
                    c.close()
        finally:
            db.DB_PATH=old
            if oldcp is None:os.environ.pop('PIM_CHECKPOINT_DIR',None)
            else:os.environ['PIM_CHECKPOINT_DIR']=oldcp
if __name__=='__main__':unittest.main()
