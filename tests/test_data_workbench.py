import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from earthworks.data_workbench import DataWorkbench,parse_upload
from earthworks.store import Store,embed


def upload():
    return {'filename':'access.csv','content':'record_id,description,project_id,gate_width_m,code\nA01,Staged truck access,P001,3.2,0007\nA02,Limited stockpile,P002,4.5,0012\n',
        'metadata':{'id':'uploaded-access','version':'v1','name':'Uploaded access evidence','record_type':'Site access observation','objective':'Assess plant and truck access','data_kind':'synthetic','available_date':'2025-01-01','source_url':''},
        'mapping':{'id':'record_id','text':'description','entities':'project_id'}}


class DataWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'workbench.sqlite',database_url='')
        self.store.ingest()
        self.workbench=DataWorkbench(self.store)

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def test_preview_then_commit_retains_original_and_connects_searchable_graph(self):
        payload=upload()
        inspected=self.workbench.inspect(payload)
        self.assertEqual(inspected['records'],2)
        preview=self.workbench.preview(payload)
        self.assertEqual(preview['entity_links'],2)
        self.assertEqual(self.store.datasets.discover('2026-01-01'),[])
        self.assertEqual(self.store.conn.execute('SELECT COUNT(*) FROM dataset_uploads').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'Preview'):
            self.workbench.commit(payload)
        result=self.workbench.commit({**payload,'preview_digest':preview['preview_digest']})
        self.assertEqual(result['records'],2)
        self.assertTrue(result['searchable'])
        hits=self.store.datasets.search('Staged truck access','2025-02-01',entity_id='P001')['matches']
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]['record']['facts']['code'],'0007')
        self.assertEqual(hits[0]['record']['source']['original_sha256'],hashlib.sha256(payload['content'].encode()).hexdigest())
        links=self.workbench.graph('P001')['edges']
        self.assertTrue(any(e['relation']=='ABOUT_ENTITY' and e['src']=='DATA:uploaded-access:v1:A01' for e in links))
        dataset_links=self.workbench.graph(result['graph_node'])['edges']
        self.assertEqual(sum(e['relation']=='HAS_RECORD' for e in dataset_links),2)
        self.assertEqual(self.workbench.source('uploaded-access','v1')['content'],payload['content'])
        catalogue=self.workbench.overview()
        item=next(d for d in catalogue['datasets'] if d['id']=='uploaded-access')
        self.assertEqual(item['objective'],payload['metadata']['objective'])
        self.assertEqual(item['record_type'],'Site access observation')
        self.assertTrue(item['has_original'])
        self.assertEqual(item['field_types']['gate_width_m'],['text'])
        self.assertEqual(self.workbench.commit({**payload,'preview_digest':preview['preview_digest']})['status'],'already imported')
        self.assertEqual(self.store.conn.execute('SELECT COUNT(*) FROM dataset_uploads').fetchone()[0],1)
        changed={**payload,'content':payload['content'].replace('3.2','6.5')}
        with self.assertRaisesRegex(ValueError,'different content'):
            self.workbench.preview(changed)
        self.assertEqual(self.workbench.source('uploaded-access','v1')['content'],payload['content'])

    def test_json_types_external_entities_and_invalid_links(self):
        payload=upload()
        payload.update(filename='context.json',content=json.dumps([{'id':'R1','text':'Ground observation','entities':['P001','region:Brisbane'],'depth_m':.7,'verified':False,'attributes':{'method':'fixture'}}]),mapping={'id':'id','text':'text','entities':'entities'})
        preview=self.workbench.preview(payload)
        self.assertEqual(preview['new_external_entities'],['region:Brisbane'])
        self.assertIn({'name':'depth_m','type':'number'},preview['fields'])
        self.workbench.commit({**payload,'preview_digest':preview['preview_digest']})
        self.assertTrue(any(e['dst']=='region:Brisbane' for e in self.workbench.graph('region:Brisbane')['edges']))
        for entities in [['P999'],['P001',17],['Brisbane']]:
            bad={**payload,'content':json.dumps([{'id':'R1','entities':entities}])}
            with self.subTest(entities=entities),self.assertRaises(ValueError):self.workbench.preview(bad)

    def test_failed_indexing_rolls_back_dataset_records_links_and_original(self):
        payload=upload();preview=self.workbench.preview(payload)
        with patch('earthworks.datasets.embed',side_effect=[embed('first'),RuntimeError('controlled indexing failure')]):
            with self.assertRaisesRegex(RuntimeError,'controlled'):
                self.workbench.commit({**payload,'preview_digest':preview['preview_digest']})
        for table in ['datasets','dataset_records','dataset_entities','dataset_uploads']:
            self.assertEqual(self.store.conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)

    def test_declared_semantics_are_available_to_the_agent_without_changing_values(self):
        from earthworks.agent import ReviewAgent
        from earthworks.budget import Budget
        from earthworks.conversation import ConversationAgent
        payload=upload()
        payload.update(filename='coded.json',content=json.dumps([{'id':'R1','distance':12,'flag':3,'entity':'P001'}]),mapping={'id':'id','entities':'entity'})
        payload['metadata']['field_definitions']={
            'distance':{'meaning':'One-way site-to-disposal haul distance','unit':'km'},
            'flag':{'meaning':'Operator screening state','value_codes':'3 = requires manual review'}}
        preview=self.workbench.preview(payload)
        self.workbench.commit({**payload,'preview_digest':preview['preview_digest']})
        agent=ConversationAgent(ReviewAgent(self.store),Budget(Path(self.temp.name)/'budget.sqlite'))
        result,definition,_,_=agent.execute({'name':'inspect_dataset_definition','arguments':json.dumps({'dataset_id':'uploaded-access','version':None})},'2026-01-01')
        self.assertEqual(definition['field_definitions']['distance']['unit'],'km')
        self.assertEqual(definition['field_definitions']['flag']['value_codes'],'3 = requires manual review')
        self.assertIn('entity',definition['undefined_fields'])
        record=self.store.datasets.get('uploaded-access','v1','R1')
        self.assertEqual(record['facts']['distance'],12)
        self.assertEqual(record['facts']['flag'],3)
        self.assertEqual(self.store.counts()['quote_lines'],21000)

    def test_structured_parser_rejects_ambiguous_or_excessive_input(self):
        for filename,content in [('bad.csv','a,a\n1,2\n'),('bad.json','[1,2]'),('bad.json','[{"x":NaN}]'),('bad.pdf','not a structured file'),('big.json',json.dumps([{'x':i} for i in range(1001)]))]:
            with self.subTest(filename=filename,content=content[:25]),self.assertRaises(ValueError):parse_upload(filename,content)

    def test_public_visibility_excludes_private_sources_from_every_evidence_path(self):
        payload=upload();payload['metadata']['data_kind']='private'
        preview=self.workbench.preview(payload)
        self.workbench.commit({**payload,'preview_digest':preview['preview_digest']})
        self.store.datasets.allow_private=False
        self.assertEqual(self.store.datasets.discover('2026-01-01'),[])
        self.assertEqual(self.store.datasets.search('access','2026-01-01')['matches'],[])
        self.assertFalse(any(e.get('source_kind')=='imported' for e in self.store.graph('P001')))
        self.assertEqual(self.workbench.overview()['datasets'],[])
        with self.assertRaises(ValueError):self.store.datasets.get('uploaded-access','v1','A01')
        with self.assertRaises(ValueError):self.store.datasets.definition('uploaded-access','2026-01-01','v1')
        with self.assertRaises(ValueError):self.workbench.source('uploaded-access','v1')


if __name__=='__main__':unittest.main()
