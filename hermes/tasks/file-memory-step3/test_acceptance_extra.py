import asyncio, json, unittest
import memory_filter as f, memory_tool as m
from test_memory_tool import MemoryTests, B, HEAD
class MoreTests(MemoryTests):
 def test_exact_5000_and_next_character(self):
  p=self.agents/'PROFILE.md'; prefix='# PROFILE\n\n'; value=HEAD+'я'*(5000-len(prefix)-1-len(HEAD))
  r=m.operate(self.user,'append','PROFILE',value); self.assertTrue(r['ok']); self.assertEqual(len(p.read_text()),5000)
  before=p.read_text(); r=m.operate(self.user,'append','PROFILE',B('x')); self.assertTrue(r['ok']); self.assertTrue(p.read_text().startswith(before))
 def test_corrupted_file_should_warn(self):
  (self.agents/'MEMORY.md').write_text('CORRUPTED FILE WITHOUT REQUIRED HEADER')
  fl=f.Filter(); fl._call_decider=lambda *args:{'misplaced':{'noul':0.01}}
  body={'messages':[{'role':'user','content':'hello'}]}; result=asyncio.run(fl.inlet(body,self.user,{})); text=result['messages'][0]['content']; self.assertIn(f.WARNING,text)
 def test_other_users_data_not_injected(self):
  import uuid
  uid=str(uuid.uuid4()); other=self.root/'bob'/'.agents'; other.mkdir(parents=True)
  for name in ('AGENTS','MEMORY','PROFILE'):(other/(name+'.md')).write_text('# '+name+'\n\nOTHER-USER-SECRET-TEST')
  self.state[uid]={'user_id':uid,'active':True,'slug':'bob','dir':'/host/users/bob'}; self.save_state()
  fl=f.Filter(); fl._call_decider=lambda *args:{'misplaced':{'noul':0.01}}
  result=asyncio.run(fl.inlet({'messages':[{'role':'user','content':'hi'}]},self.user,{})); self.assertNotIn('OTHER-USER-SECRET-TEST',json.dumps(result))
if __name__=='__main__':unittest.main()
