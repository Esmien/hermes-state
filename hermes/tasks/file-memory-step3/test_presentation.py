import asyncio,json,unittest
import memory_tool as m, memory_filter as f
from test_memory_filter import FilterTests
from test_memory_tool import B
class DeterministicPresentationTests(FilterTests):
 def prepare(self,stage):
  for x in ('alpha','beta','gamma','delta','epsilon'):m.operate(self.user,'append','MEMORY',B(x))
  self.set_stage(stage)
 def outlet(self):
  message={'role':'assistant','content':'Обычный ответ','output':[{'type':'message','content':[{'type':'output_text','text':'Обычный ответ'}]}]}
  body={'messages':[message]}; asyncio.run(self.filter.outlet(body,self.user,{})); return body,message
 def test_offer_is_complete_and_idempotent(self):
  self.prepare('offer'); b,msg=self.outlet(); text=msg['content']; self.assertIn('автоматическое сообщение, не ответ модели',text); self.assertIn('для выбора используйте только точный список ниже',text); self.assertIn('1. - **Ключ:** alpha',text); self.assertIn('5. - **Ключ:** epsilon\n\nРекомендуется удалить 1 записей',text)
  self.assertEqual(msg['output'][0]['content'][0]['text'],text); asyncio.run(self.filter.outlet(b,self.user,{})); self.assertEqual(msg['content'],text)
 def test_short_reminders_and_list_on_request(self):
  self.prepare('offer'); before=(self.agents/'MEMORY.md').read_text()
  _,first=self.outlet(); self.assertIn('1. - **Ключ:** alpha',first['content'])
  _,second=self.outlet(); self.assertIn('Напоминание:',second['content']); self.assertNotIn('1. - **Ключ:** alpha',second['content']); self.assertNotIn('Системное уведомление памяти',second['content'])
  self.answers['intent']['choice']='edit'; self.run_filter(self.body(prev=second['content'],user='Покажи список'))
  _,third=self.outlet(); self.assertIn('Системное уведомление памяти',third['content']); self.assertIn('1. - **Ключ:** alpha',third['content']); self.assertIn('5. - **Ключ:** epsilon',third['content']); self.assertEqual((self.agents/'MEMORY.md').read_text(),before)
 def test_no_presentable_assistant_does_not_mark_offered(self):
  self.prepare('offer'); asyncio.run(self.filter.outlet({'messages':[{'role':'assistant','output':[]}]},self.user,{})); _,message=self.outlet(); self.assertIn('1. - **Ключ:** alpha',message['content'])
 def test_refusal_reminds_without_mutation(self):
  self.prepare('refused'); before=(self.agents/'MEMORY.md').read_text(); _,msg=self.outlet(); self.assertIn('Напоминание:',msg['content']); self.assertEqual((self.agents/'MEMORY.md').read_text(),before)
 def test_confirm_show_and_close(self):
  self.prepare('confirm'); _,msg=self.outlet(); self.assertIn('Системное уведомление памяти',msg['content']); self.assertIn('5. - **Ключ:** epsilon\n\nОставляем или есть правки?',msg['content'])
  self.answers['intent']['choice']='confirm'; self.answers['notice_seen']['noul']=1.0
  self.run_filter(self.body(prev=msg['content'],user='Да, оставляем')); self.assertEqual(self.get_stage(),'completed')
  _,msg=self.outlet(); self.assertIn('Сохранено, можем продолжить разговор',msg['content']); self.assertEqual(json.loads((self.agents/'.memory-state.json').read_text())['overflow'],{})
 def test_corrupt_outlet_warns(self):
  (self.agents/'PROFILE.md').write_text('corrupt'); _,msg=self.outlet(); self.assertTrue(msg['content'].startswith(f.WARNING))
if __name__=='__main__':unittest.main()
