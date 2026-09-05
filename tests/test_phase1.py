import json
import tempfile
import unittest
from pathlib import Path

from novel_agent.core.bible import Bible, Character
from novel_agent.core.chapter import ChapterPlan, ChapterStore
from novel_agent.core.continuity import Continuity
from novel_agent.core.ideas import IdeaBank
from novel_agent.core.outline import Outline, Volume
from novel_agent.core.search import SearchEngine
from novel_agent.core.world import World
from novel_agent.core.threads import ThreadNetwork
from novel_agent.core.memory import Memory, ContextBundle


class FakeEmbedder:
    model = "fake-model"
    dim = 4

    def embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return [[float(len(t)), 1.0, 0.0, 0.0] for t in texts]

    def embed_one(self, text):
        return self.embed([text])[0]


class Phase1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root.mkdir(exist_ok=True)
        self.store = ChapterStore()
        self.bible = Bible(project="p", characters=[Character(id="char_001", name="林尘", summary="主角")])
        self.world = World(project="p")
        self.cont = Continuity(project="p")
        self.ideas = IdeaBank(project="p")
        self.outline = Outline(project="p", volumes=[Volume(volume_id="v1", chapters=[ChapterPlan(chapter_id="c001", title="开端", beat="林尘出发")])])

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, embed=True):
        e = SearchEngine(self.root)
        e.index_project(bible=self.bible, continuity=self.cont, world=self.world, ideas=self.ideas, store=self.store, project_dir=self.root, embedder=FakeEmbedder() if embed else None)
        return e

    def test_idea_stale_and_rebuild(self):
        e = self.build()
        self.ideas.add("神秘地图", title="地图")
        self.ideas.save(self.root)
        self.assertTrue(e.is_stale(vector_model="fake-model"))
        e.ensure_index_fresh(bible=self.bible, continuity=self.cont, world=self.world, ideas=self.ideas, store=self.store, project_dir=self.root, embedder=FakeEmbedder())
        self.assertIn("idea:i_001", e.docs)

    def test_chapter_stale_and_rebuild(self):
        e = self.build(embed=False)
        self.store.write_chapter(self.root, self.outline.find("c001"), "新章节内容", "摘要", source="test")
        self.assertTrue(e.is_stale())
        e.ensure_index_fresh(bible=self.bible, continuity=self.cont, world=self.world, ideas=self.ideas, store=self.store, project_dir=self.root)
        self.assertIn("chapter:c001:chunk:1", e.docs)

    def test_bible_change_stale(self):
        e = self.build(embed=False)
        self.bible.characters[0].summary = "修改"
        self.bible.save(self.root)
        self.assertTrue(e.is_stale())

    def test_corrupt_vectors_rejected(self):
        e = self.build()
        p = self.root / "embeddings" / "vec.npy"
        import numpy as np
        np.save(p, np.zeros((0, 4), dtype=np.float32))
        with self.assertRaises(RuntimeError):
            e.search_semantic("林尘", FakeEmbedder())

    def test_context_bundle_and_compatibility(self):
        mem = Memory(self.root, self.outline, self.bible, self.store, self.cont, world=self.world, ideas=self.ideas, threads=ThreadNetwork(project="p"))
        bundle = mem.build_context_bundle("c001")
        self.assertIsInstance(bundle, ContextBundle)
        for attr in ("text", "deterministic_sources", "selected_ideas", "retrieved_sources", "constraints"):
            self.assertTrue(hasattr(bundle, attr))
        self.assertIsInstance(mem.build_context_for_chapter("c001"), str)


if __name__ == "__main__":
    unittest.main()
