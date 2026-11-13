import asyncio,json,unittest
import memory_filter as f
from test_memory_filter import FilterTests
class StreamGuardTests(FilterTests):
 def test_warning_only_in_stream_and_outlet(self):
  self.set_stage('offer'); self.answers['intent']['choice']='ignore'; meta={'chat_id':'chat-1','message_id':'msg-1'}
  self.run_filter(self.body(prev='Memory is full. Choose records to delete.'),metadata=meta)
  chunks=[{'choices':[{'delta':{'content':'4. Без вашего ответа '}}]},{'choices':[{'delta':{'content':'я ничего не удаляю.'}}]}]
  pieces=[]
  for event in chunks: pieces.append(asyncio.run(self.filter.stream(event,self.user,meta))['choices'][0]['delta']['content'])
  self.assertEqual(''.join(pieces),f.FULL_WARNING)
  msg={'role':'assistant','content':'4. Без вашего ответа я ничего не удаляю.','output':[{'type':'message','content':[{'type':'output_text','text':'противоречие'}]}]}
  asyncio.run(self.filter.outlet({'messages':[msg]},self.user,meta)); self.assertEqual(msg['content'],f.FULL_WARNING); self.assertEqual(msg['output'][0]['content'][0]['text'],f.FULL_WARNING)
  self.assertTrue(json.loads((self.agents/'.memory-state.json').read_text())['overflow']['MEMORY']['guarded'])
 def test_no_stream_proof_no_delete(self):
  self.set_stage('warning'); self.answers['intent']['choice']='ignore'; calls=[]
  async def delete(*args):calls.append(True); return 'deleted'
  self.filter._delete_first_ten=delete; self.run_filter(self.body(prev=f.FULL_WARNING)); self.assertEqual(calls,[]); self.assertEqual(self.get_stage(),'warning')
if __name__=='__main__':unittest.main()
