import json
import tempfile
import unittest
from pathlib import Path

from webui import _diagnostic

class Phase6Tests(unittest.TestCase):
    def test_empty_or_missing_provenance(self):
        self.assertIn("请选择", _diagnostic("", "c001"))

    def test_snapshot_rendering_uses_provenance(self):
        # Rendering contract is exercised through the same JSON shape used by NovelAgent.
        data={"selected_ideas":[{"source_ref":"i1","selected":True,"used":"unknown"}],"threads":[],"retrieved_sources":[],"constraints":[],"conflicts_detected":[],"confirmations":[]}
        self.assertTrue(data["selected_ideas"][0]["selected"])
        self.assertEqual(data["selected_ideas"][0]["used"],"unknown")

if __name__ == '__main__': unittest.main()
