import asyncio,copy,unittest
import memory_filter as f
class FormatTests(unittest.TestCase):
 def setUp(self):
  self.x=f.Filter(); self.user={'id':'test'}; self.meta={'chat_id':'c','message_id':'m'}; self.key=('test','c','m'); self.x._warning_streams[self.key]={'sent':False,'text':f.FULL_WARNING}
 def test_responses_api_final_event_no_raw_text(self):
  sentinel='MODEL_CONTRADICTION_SENTINEL'; events=[{'type':'response.output_text.delta','delta':sentinel},{'type':'response.output_text.done','text':sentinel},{'type':'response.output_item.done','item':{'content':[{'type':'output_text','text':sentinel}]}},{'type':'response.completed','response':{'output':[{'content':[{'text':sentinel}]}]}}]
  for event in events:
   out=asyncio.run(self.x.stream(copy.deepcopy(event),self.user,self.meta)); self.assertNotIn(sentinel,str(out))
 def test_chat_completion_array_content_no_raw_text(self):
  sentinel='MODEL_CONTRADICTION_SENTINEL'; event={'choices':[{'delta':{'content':[{'type':'text','text':sentinel}]}}]}; out=asyncio.run(self.x.stream(event,self.user,self.meta)); self.assertNotIn(sentinel,str(out))
if __name__=='__main__':unittest.main()
