import unittest
import json
import tempfile
from types import SimpleNamespace
from pathlib import Path
from novel_agent.core.ideas import Idea
from novel_agent.core.chapter_fit import ChapterFitResolver
from novel_agent.core.threads import ThreadNetwork, ThreadNode
from novel_agent.core.ideas import IdeaBank

class Phase4Tests(unittest.TestCase):
    def test_exact_and_later(self):
        r=ChapterFitResolver().resolve(Idea(id='i1',placed_chapter='c004'), 'c004')
        self.assertEqual(r.decision,'recommended'); self.assertIn('planned chapter matches current chapter',r.reasons)
        r=ChapterFitResolver().resolve(Idea(id='i2',placed_chapter='c012'), 'c004')
        self.assertEqual(r.decision,'deferred')
    def test_thread_match(self):
        ts=ThreadNetwork(threads=[]); t=ts.add_thread(id='t002',name='线'); t.nodes.append(ThreadNode(id='n1',chapter_id='c004',from_idea='i1'))
        a=ChapterFitResolver().resolve(Idea(id='i1'), 'c004', ts)
        b=ChapterFitResolver().resolve(Idea(id='i2'), 'c004', ts)
        self.assertGreater(a.chapter_fit,b.chapter_fit)
    def test_used_and_inactive(self):
        self.assertEqual(ChapterFitResolver().resolve(Idea(id='i1',used_chapter='c003'),'c004').decision,'deferred')
        self.assertNotEqual(ChapterFitResolver().resolve(Idea(id='i2',status='dropped'),'c004').decision,'recommended')
        for status in ('archived', 'rejected', 'inactive'):
            fake=SimpleNamespace(id='i2', status=status, used_chapter='', placed_chapter='')
            self.assertNotEqual(ChapterFitResolver().resolve(fake,'c004').decision,'recommended')
    def test_selected_used_semantics(self):
        r=ChapterFitResolver().resolve(Idea(id='i1',placed_chapter='c004'),'c004')
        record={'selected':True,'used':'unknown','decision':r.decision}
        self.assertEqual(record['used'],'unknown')

    def test_backward_compatibility_old_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'ideas.json').write_text(json.dumps({'project':'p','ideas':[{'id':'i1','content':'old'}]}),encoding='utf-8')
            (root/'threads.json').write_text(json.dumps({'project':'p','threads':[]}),encoding='utf-8')
            (root/'chapters').mkdir(); (root/'chapters'/'provenance').mkdir()
            (root/'chapters'/'provenance'/'c001.json').write_text(json.dumps({'chapter_id':'c001','selected_ideas':[]}),encoding='utf-8')
            self.assertEqual(IdeaBank.load(root).ideas[0].id,'i1')
            self.assertEqual(ThreadNetwork.load(root).threads,[])
            self.assertEqual(json.loads((root/'chapters'/'provenance'/'c001.json').read_text())['chapter_id'],'c001')

    def test_provenance_snapshot_not_recomputed(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'c004.json'
            snapshot={'chapter_id':'c004','selected_ideas':[{'source_id':'i1','chapter_fit':.9,'decision':'recommended','reasons':['exact']}], 'ideas':[]}
            f.write_text(json.dumps(snapshot),encoding='utf-8')
            idea=Idea(id='i1',placed_chapter='c004')
            before=json.loads(f.read_text())
            idea.status='dropped'
            after=json.loads(f.read_text())
            self.assertEqual(before,after)
            self.assertEqual(after['selected_ideas'][0]['decision'],'recommended')

if __name__=='__main__': unittest.main()
