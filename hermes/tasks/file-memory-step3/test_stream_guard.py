import asyncio
from test_memory_filter import FilterTests
import memory_filter as f

class ReminderTests(FilterTests):
 def test_reminder_added_to_outlet_without_erasing_answer(self):
  self.set_stage('refused'); msg={'role':'assistant','content':'Ответ 4.'}; asyncio.run(self.filter.outlet({'messages':[msg]},self.user,{})); self.assertIn('Ответ 4.',msg['content']); self.assertIn('Напоминание',msg['content']); self.assertIn('ничего не удаляю',msg['content'])
 def test_no_stream_suppression_or_auto_delete(self):
  self.assertFalse(hasattr(self.filter,'stream')); self.assertFalse(hasattr(self.filter,'_delete_first_ten'))
