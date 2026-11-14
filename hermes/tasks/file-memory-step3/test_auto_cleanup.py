import memory_tool as m
from test_memory_filter import FilterTests
from test_memory_tool import B

class NoAutomaticCleanupTests(FilterTests):
 def test_repeat_ignore_preserves_all_entries(self):
  for i in range(12): m.operate(self.user,'append','MEMORY',B(f'synthetic-{i+1}'))
  original=m.operate(self.user,'list','MEMORY')['entries']; self.set_stage('offer'); self.answers['intent']['choice']='ignore'
  for _ in range(4): self.run_filter(self.body())
  self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'],original)
  self.assertEqual(self.get_stage(),'offer')
 def test_old_warning_state_migrates_without_deletion(self):
  m.operate(self.user,'append','MEMORY',B('keep')); self.set_stage('warning'); self.answers['intent']['choice']='ignore'; self.run_filter(self.body()); self.assertEqual(self.get_stage(),'offer'); self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'],[B('keep')])
