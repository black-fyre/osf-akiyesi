"""CLAUDE.md required test:
- Adding a community requires a config row and no code change.

Proved by loading an alternate config/ directory (a temp copy of the real
one with one extra community row appended) and showing the pipeline routes
reports for it correctly -- with zero changes to app/*.py.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from app.config import load_config, REPO_ROOT
from app.llm import RuleBasedClient
from app.storage import make_store
from app.pipeline import process_inbound, STATUS_STORED


class ConfigScalabilityTests(unittest.TestCase):
    def test_new_community_is_a_config_only_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_config_dir = Path(tmp) / "config"
            shutil.copytree(REPO_ROOT / "config", tmp_config_dir)

            communities_path = tmp_config_dir / "communities.yaml"
            data = yaml.safe_load(communities_path.read_text(encoding="utf-8"))
            data["communities"].append(
                {
                    "id": "new-estate-42",
                    "name": "New Estate 42 Residents Association",
                    "locale": "en-NG",
                    "normal_inbound": "40404*REPORT-NEWESTATE42",
                    "protected_inbound": "40404*SAFE-NEWESTATE42",
                    "protected_recipients": [{"name": "New Estate 42 Landlord Association", "contact": "x@example.org"}],
                    "desk_recipients": [{"name": "New Estate 42 Security Committee", "contact": "y@example.org"}],
                    "thresholds": {},
                }
            )
            communities_path.write_text(yaml.safe_dump(data), encoding="utf-8")

            config = load_config(config_dir=tmp_config_dir)
            self.assertIn("new-estate-42", config.communities)

            llm = RuleBasedClient()
            store = make_store(":memory:")
            payload = {
                "id": "new-estate-1",
                "to": "40404*REPORT-NEWESTATE42",
                "from": "+2348066660001",
                "text": "Someone was checking gates along our new street.",
            }
            report = process_inbound(payload, config, llm, store)
            self.assertEqual(report.status, STATUS_STORED)
            self.assertEqual(report.community_id, "new-estate-42")


if __name__ == "__main__":
    unittest.main()
