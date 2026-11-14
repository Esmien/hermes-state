import asyncio, os, unittest
from unittest.mock import patch
import memory_tool as m
from test_memory_tool import MemoryTests, B, HEAD
import memory_filter as f

class SoftLimitTests(MemoryTests):
 def fill(self):
  (self.agents/'MEMORY.md').write_text('# MEMORY\n\n'+('x'*(m.LIMIT//20-10)+'\n\n')*20)
 def test_crossing_blocks_next_and_no_auto_removal(self):
  self.fill(); r=m.operate(self.user,'append','MEMORY',HEAD+'y'*(m.RECORD_LIMIT-len(HEAD))); self.assertTrue(r['ok']); self.assertTrue(r['overflow']); initial=m.operate(self.user,'list','MEMORY')['entries']; self.assertEqual(m.operate(self.user,'append','MEMORY',B('new'))['reason'],'memory_full'); self.assertEqual(initial,m.operate(self.user,'list','MEMORY')['entries'])
 def test_partial_delete_while_over_limit(self):
  self.fill(); p=self.agents/'MEMORY.md'; p.write_text(p.read_text()+'small\n\n'); m.operate(self.user,'append','MEMORY',HEAD+'y'*(m.RECORD_LIMIT-len(HEAD))); result=m.operate(self.user,'delete','MEMORY',selected=[{'number':21,'text':'small'}]); self.assertTrue(result['ok']); self.assertTrue(result['overflow']); fd=m._open_dir(self.user)
  try:self.assertEqual(m._load_state(fd)['overflow']['MEMORY']['stage'],'offer')
  finally:os.close(fd)
 def test_length_recovered_after_lost_state(self):
  self.fill(); m.operate(self.user,'append','MEMORY',HEAD+'y'*(m.RECORD_LIMIT-len(HEAD))); fd=m._open_dir(self.user)
  try:m._save_state(fd,{'version':1,'overflow':{}})
  finally:os.close(fd)
  x=f.Filter(); x._call_decider=lambda *a: {'misplaced':{'noul':0}}
  asyncio.run(x.inlet({'messages':[{'role':'user','content':'Привет'}]},self.user,{})); fd=m._open_dir(self.user)
  try:self.assertEqual(m._load_state(fd)['overflow']['MEMORY']['stage'],'offer')
  finally:os.close(fd)
 def test_state_failure_reports_success_and_recovers_from_file(self):
  self.fill()
  with patch.object(m,'_save_state',side_effect=OSError('synthetic')):
   r=m.operate(self.user,'append','MEMORY',HEAD+'y'*(m.RECORD_LIMIT-len(HEAD)))
  self.assertTrue(r['ok']); self.assertTrue(r['state_warning']); self.assertTrue(r['overflow']); self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'][-1],HEAD+'y'*(m.RECORD_LIMIT-len(HEAD)))
  x=f.Filter(); x._call_decider=lambda *a:{'misplaced':{'noul':0}}
  asyncio.run(x.inlet({'messages':[{'role':'user','content':'Привет'}]},self.user,{})); fd=m._open_dir(self.user)
  try:self.assertEqual(m._load_state(fd)['overflow']['MEMORY']['stage'],'offer')
  finally:os.close(fd)
 def test_profile_without_limit(self):
  result=m.operate(self.user,'append','PROFILE',B('q'*20000)); self.assertTrue(result['ok']); self.assertIsNone(result['limit']); self.assertFalse(result['overflow'])
 def test_exact_limit_blocks_new_and_sets_pending(self):
  (self.agents/'MEMORY.md').write_text('# MEMORY\n\n'+'x'*(m.LIMIT-len('# MEMORY\n\n'))); r=m.operate(self.user,'append','MEMORY',B('q')); self.assertFalse(r['ok']); fd=m._open_dir(self.user)
  try:self.assertEqual(m._load_state(fd)['overflow']['MEMORY']['stage'],'offer')
  finally:os.close(fd)
if __name__=='__main__':unittest.main()
