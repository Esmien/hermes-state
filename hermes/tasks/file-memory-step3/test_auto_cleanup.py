import asyncio,json,unittest
import memory_tool as m, memory_filter as f
from test_memory_filter import FilterTests
class AutoCleanupTests(FilterTests):
 def setUp(self):
  super().setUp(); self.calls=0
  for i in range(12):m.operate(self.user,'append','MEMORY',f'synthetic-{i+1}')
  self.original=m.operate(self.user,'list','MEMORY')['entries']; self.set_stage('warning'); self._guard(); self.answers['intent']['choice']='ignore'
  async def delete(request,user,name):
   self.calls+=1; values=m.operate(user,'list',name)['entries']
   if len(values)<10:return 'too_few'
   result=m.operate(user,'delete',name,selected=[{'number':i+1,'text':v} for i,v in enumerate(values[:10])]); return 'deleted' if result['ok'] else 'failed'
  self.filter._delete_first_ten=delete
 def _guard(self):
  p=self.agents/'.memory-state.json'; state=json.loads(p.read_text()); state['overflow']['MEMORY']['guarded']=True; p.write_text(json.dumps(state))
 def test_second_ignore_exactly_ten(self):
  self.run_filter(self.body(prev=f.FULL_WARNING)); self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'],self.original[10:]); self.assertEqual(self.calls,1); self.assertEqual(self.get_stage(),'confirm')
  msg={'role':'assistant','content':'answer'}; asyncio.run(self.filter.outlet({'messages':[msg]},self.user,{})); self.assertTrue(msg['content'].startswith('Автоматически удалены первые 10')); self.assertIn('Оставляем или есть правки?',msg['content'])
  self.run_filter(self.body(prev='new',user='unrelated')); self.assertEqual(self.calls,1)
 def test_explicit_refusal_and_missing_warning(self):
  self.answers['intent']['choice']='refuse'; self.run_filter(self.body(prev=f.FULL_WARNING)); self.assertEqual(self.calls,0); self.assertEqual(self.get_stage(),'refused'); self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'],self.original)
  self.set_stage('warning'); self.answers['intent']['choice']='ignore'; self.run_filter(self.body(prev='no warning')); self.assertEqual(self.calls,0); self.assertEqual(self.get_stage(),'warning')
 def test_failure_after_possible_side_effect_not_retried(self):
  async def broken(request,user,name):
   self.calls+=1; values=m.operate(user,'list',name)['entries']; m.operate(user,'delete',name,selected=[{'number':i+1,'text':v} for i,v in enumerate(values[:10])]); raise RuntimeError('simulated post-write failure')
  self.filter._delete_first_ten=broken; self.run_filter(self.body(prev=f.FULL_WARNING)); self.assertEqual(self.get_stage(),'blocked'); self.run_filter(self.body(prev=f.FULL_WARNING)); self.assertEqual(self.calls,1); self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'],self.original[10:])
 def test_fewer_than_ten_blocked(self):
  m.operate(self.user,'delete','MEMORY',selected=[{'number':i+1,'text':v} for i,v in enumerate(self.original[:4])]); self.set_stage('warning'); self._guard(); before=m.operate(self.user,'list','MEMORY')['entries']; self.run_filter(self.body(prev=f.FULL_WARNING)); self.assertEqual(self.get_stage(),'blocked'); self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'],before)
if __name__=='__main__':unittest.main()
