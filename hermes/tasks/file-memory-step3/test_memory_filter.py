import asyncio
import copy
import json
from pathlib import Path
import unittest
import memory_filter as f
import memory_tool as m
from test_memory_tool import MemoryTests

class FilterTests(MemoryTests):
    def setUp(self):
        super().setUp()
        self.filter=f.Filter()
        self.answers={'misplaced':{'noul':0.01},'intent':{'choice':'unclear'},'notice_seen':{'noul':1.0}}
        self.filter._call_decider=lambda *args: self.answers
    def body(self, prev='Review your memory', user='hello'):
        return {'messages':[{'role':'system','content':'ADMIN'},{'role':'assistant','content':prev},{'role':'user','content':user}]}
    def run_filter(self, body, user=None, metadata=None, answers=None):
        if answers is not None:
            self.filter._call_decider=lambda *a: answers
        return asyncio.run(self.filter.inlet(body, self.user if user is None else user, metadata or {}))
    def set_stage(self,stage):
        (self.agents/'.memory-state.json').write_text(json.dumps({'version':1,'overflow':{'MEMORY':{'stage':stage}}}))
    def get_stage(self):
        return json.loads((self.agents/'.memory-state.json').read_text())['overflow']['MEMORY']['stage']
    def test_global_scope_and_tool_injection(self):
        u={**self.user, 'role':'user'}
        b=self.body(); b['tool_ids']=['existing_tool']; out=self.run_filter(b,user=u)
        self.assertEqual(out['tool_ids'],['existing_tool',self.filter.valves.tool_id])
        self.assertEqual(self.run_filter(out,user=u)['tool_ids'],['existing_tool',self.filter.valves.tool_id])
        explicit=self.body(); explicit['tools']=[]; self.assertNotIn('tool_ids',self.run_filter(explicit,user=u))
        bad=self.body(); self.assertNotIn('tool_ids',self.run_filter(bad,user={'role':'user','id':'bad'}))
        admin={**self.user,'role':'admin'}; b=self.body(); out=self.run_filter(b,user=admin)
        self.assertIn(f.BEGIN,out['messages'][0]['content'])
        self.assertIn(self.filter.valves.tool_id,out['tool_ids'])
    def test_stable_single_block_admin_intact(self):
        b=self.run_filter(self.body()); first=b['messages'][0]['content']
        self.assertEqual(first.count(f.BEGIN),1)
        self.assertEqual(first.count(f.END),1)
        self.assertTrue(first.startswith('ADMIN'))
        self.assertIn('260 символов — потолок, а не цель', first)
        self.assertIn('без потери значимых фактов', first)
        self.assertLess(first.index('[AGENTS]'),first.index('[MEMORY]'))
        self.assertLess(first.index('[MEMORY]'),first.index('[PROFILE]'))
        second=self.run_filter(b)['messages'][0]['content']
        self.assertEqual(first,second)
    def test_task_not_processed(self):
        b=self.body(); old=copy.deepcopy(b)
        self.assertEqual(self.run_filter(b,metadata={'task':'title_generation'}),old)
        self.assertEqual(self.run_filter(b,metadata={'internal':True}),old)
    def test_missing_user_warns_without_other_memory(self):
        b=self.run_filter(self.body(),user={'id':'not-a-uuid'})
        text=b['messages'][0]['content']; self.assertIn(f.WARNING,text); self.assertNotIn('[PROFILE]',text)
    def test_overflow_ignored_twice_and_missing_warning(self):
        m.operate(self.user,'append','MEMORY','synthetic')
        self.set_stage('offer'); self.answers['intent']['choice']='ignore'
        before=m.operate(self.user,'list','MEMORY')['entries']
        for _ in range(3):
            b=self.run_filter(self.body()); self.assertEqual(self.get_stage(),'offer'); self.assertIn('переполнена',b['messages'][0]['content'].lower())
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'],before)
    def test_refusal_never_deletes(self):
        self.set_stage('warning'); self.answers['intent']['choice']='refuse'
        b=self.run_filter(self.body()); self.assertEqual(self.get_stage(),'refused'); self.assertIn('ничего не удаляй',b['messages'][0]['content'].lower())
    def test_decider_failure_does_not_advance_or_delete(self):
        self.set_stage('warning')
        def fail(*args): raise ValueError('test')
        self.filter._call_decider=fail
        b=self.run_filter(self.body()); self.assertEqual(self.get_stage(),'warning'); self.assertIn('не удаляй',b['messages'][0]['content'].lower())
    def test_markers_collisions_rejected(self):
        (self.agents/'MEMORY.md').write_text('# MEMORY\n\n'+f.BEGIN)
        b=self.run_filter(self.body()); self.assertIn(f.WARNING,b['messages'][0]['content'])
    def test_outlet_adds_warning_to_content_and_structured_output_once(self):
        self.set_stage('warning')
        message={'role':'assistant','content':'Ответ', 'output':[{'type':'message','content':[{'type':'output_text','text':'Ответ'}]}]}
        body={'messages':[message]}
        asyncio.run(self.filter.outlet(body,self.user,{}))
        asyncio.run(self.filter.outlet(body,self.user,{}))
        self.assertEqual(message['content'].count(f.FULL_WARNING),1)
        self.assertEqual(message['output'][0]['content'][0]['text'].count(f.FULL_WARNING),1)
    def test_outlet_missing_user_warning(self):
        body={'messages':[{'role':'assistant','content':'Ответ'}]}
        asyncio.run(self.filter.outlet(body,{'id':'invalid'},{}))
        self.assertTrue(body['messages'][0]['content'].startswith(f.WARNING))
    def test_real_overflow_records_state(self):
        (self.agents/'MEMORY.md').write_text('# MEMORY\n\n' + ('x'*240+'\n\n')*20)
        result=m.operate(self.user,'append','MEMORY','y'*260)
        self.assertTrue(result['ok']); self.assertTrue(result['overflow'])
        state=json.loads((self.agents/'.memory-state.json').read_text())
        self.assertEqual(state['overflow']['MEMORY']['stage'],'offer')

if __name__=='__main__': unittest.main()

class AutoFileTests(FilterTests):
    """Записи не по адресу переносит фильтр: новая запись плюс удаление старой."""
    def classify(self, mapping):
        calls={}
        def fake(items):
            calls['items']=[x['text'] for x in items]
            return {x['id']: mapping[x['text']] for x in items if x['text'] in mapping}
        self.filter._classify=fake
        return calls
    def test_move_memory_to_profile(self):
        text='У неё две кошки, Крис и Вася.'
        m.operate(self.user,'append','MEMORY',text)
        m.operate(self.user,'append','PROFILE','Живёт в Ванино.')
        calls=self.classify({text:'PROFILE'})
        out=self.run_filter(self.body())
        self.assertIn(text,calls['items'])
        self.assertNotIn(text,m.operate(self.user,'list','MEMORY')['entries'])
        self.assertEqual(m.operate(self.user,'list','PROFILE')['entries'][-1],text)
        self.assertIn('фильтр памяти',out['messages'][0]['content'])
        state=json.loads((self.agents/'.memory-state.json').read_text())
        self.assertEqual(state['moves'][-1],{'from':'MEMORY','to':'PROFILE','chars':len(text)})
        self.assertTrue(state['checked'])
        self.run_filter(self.body()); self.run_filter(self.body())
        self.assertEqual(len(json.loads((self.agents/'.memory-state.json').read_text())['moves']),1)
    def test_no_move_without_sure_target(self):
        text='Заметка про проект.'
        m.operate(self.user,'append','MEMORY',text)
        self.classify({})
        self.run_filter(self.body())
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'],[text])
        state=json.loads((self.agents/'.memory-state.json').read_text())
        self.assertTrue(state['checked'])
        self.assertNotIn('moves',state)
    def test_agents_is_never_auto_target(self):
        text='Правило: отвечать кратко.'
        m.operate(self.user,'append','MEMORY',text)
        self.classify({text:'AGENTS'})
        self.run_filter(self.body())
        self.assertEqual(m.operate(self.user,'list','MEMORY')['entries'],[text])
        self.assertEqual(m.operate(self.user,'list','AGENTS')['entries'],[])
    def test_move_into_memory_respects_limit(self):
        long_rule='Правило: '+'я'*280
        m.operate(self.user,'append','PROFILE',long_rule)
        m.operate(self.user,'append','MEMORY','x'*250)
        self.classify({long_rule:'MEMORY'})
        self.run_filter(self.body())
        self.assertIn(long_rule,m.operate(self.user,'list','PROFILE')['entries'])
