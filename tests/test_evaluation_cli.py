"""Evaluation CLI command parsing and Compact Graph generation tests."""

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simulation.evaluation import cli
from tests.fixtures import load_graph


class EvaluationCliTest(unittest.TestCase):
    def test_parser_selects_compare_command(self):
        args = cli.build_parser().parse_args(
            ["compare", "--start", "1", "--goal", "3", "--dry-run"]
        )

        self.assertEqual(args.start, 1)
        self.assertEqual(args.goal, 3)
        self.assertTrue(args.dry_run)
        self.assertIs(args.handler, cli.run_compare)

    def test_route_file_rejects_parent_traversal(self):
        with self.assertRaisesRegex(ValueError, "routes 폴더"):
            cli.route_file("../outside.geojson")

    def test_build_compact_writes_selected_output(self):
        with tempfile.TemporaryDirectory() as directory:
            route_dir = Path(directory)
            source = route_dir / "source.geojson"
            source.write_text(
                json.dumps(load_graph(), ensure_ascii=False),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                source=source.name,
                output="compact.geojson",
            )

            with patch.object(cli, "ROUTE_DIR", route_dir):
                status = cli.run_build_compact(args)

            output = json.loads(
                (route_dir / "compact.geojson").read_text(encoding="utf-8")
            )
            self.assertEqual(status, 0)
            self.assertEqual(output["type"], "CompactRouteGraph")
            self.assertEqual(output["source_graph"], source.name)


if __name__ == "__main__":
    unittest.main()
