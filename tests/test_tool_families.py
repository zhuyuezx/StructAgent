from __future__ import annotations

import unittest
from unittest.mock import patch

from core.perception.canvas import tool_families


class ToolFamiliesTest(unittest.TestCase):
    def test_repeated_rectangle_tools_create_family_with_unsuffixed_default(self) -> None:
        families = tool_families({
            "Rectangle_Tool": {},
            "Rectangle_Tool_1": {},
            "Cloud_Tool": {},
        })

        self.assertEqual(families["Rectangle_Family"]["default"], "Rectangle_Tool")
        self.assertEqual(
            families["Rectangle_Family"]["candidates"],
            ["Rectangle_Tool", "Rectangle_Tool_1"],
        )

    def test_configured_default_wins_when_candidate_exists(self) -> None:
        with patch("core.perception.canvas.config.tool_families", return_value={
            "Rectangle_Family": {
                "default": "Rectangle_Tool_1",
                "candidates": ["Rectangle_Tool", "Rectangle_Tool_1"],
            }
        }):
            families = tool_families({
                "Rectangle_Tool": {},
                "Rectangle_Tool_1": {},
            })

        self.assertEqual(families["Rectangle_Family"]["default"], "Rectangle_Tool_1")

    def test_configured_empty_family_is_omitted(self) -> None:
        with patch("core.perception.canvas.config.tool_families", return_value={
            "Ellipse_Family": {
                "default": "Ellipse_Tool",
                "candidates": ["Ellipse_Tool"],
            }
        }):
            families = tool_families({"Rectangle_Tool": {}})

        self.assertNotIn("Ellipse_Family", families)


if __name__ == "__main__":
    unittest.main()
