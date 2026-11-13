import unittest,importlib.util,asyncio
from test_memory_tool import MemoryTests
class BuiltFilterTests(MemoryTests):
 def setUp(self):
  super().setUp(); spec=importlib.util.spec_from_file_location('built_filter','built/memory_filter.py'); self.b=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.b)
  self.b.ROOT=str(self.root); self.b.HOST_ROOT='/host/users'; self.b.STATE=str(self.tmp.name)+'/state.json'; self.f=self.b.Filter(); self.f._call_decider=lambda *args:{'misplaced':{'noul':0.01}}
 def test_built_filter_reads_real_format(self):
  body={'messages':[{'role':'user','content':'hello'}]}; result=asyncio.run(self.f.inlet(body,self.user,{})); self.assertIn('[MEMORY]',result['messages'][0]['content']); self.assertNotIn(self.b.WARNING,result['messages'][0]['content'])
 def test_built_filter_works_for_offer(self):
  import json
  (self.agents/'.memory-state.json').write_text(json.dumps({'version':1,'overflow':{'MEMORY':{'stage':'offer'}}}))
  msg={'role':'assistant','content':'answer'}; asyncio.run(self.f.outlet({'messages':[msg]},self.user,{})); self.assertIn('Память MEMORY переполнена',msg['content']); self.assertNotIn(self.b.WARNING,msg['content'])
if __name__=='__main__':unittest.main()
