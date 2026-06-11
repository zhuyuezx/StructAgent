import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.agents import critic


def test_critic_salvages_partial_reasoning_json_as_failure():
    raw = """{
 "reasoning": "The screenshot shows a single shape on the canvas. However, the shape is a trapezoid, not a rectangle. The label 'Rectangle1' is present"""

    result = critic._salvage_critic_reply(raw)

    assert result == {
        "passed": False,
        "reasoning": (
            "The screenshot shows a single shape on the canvas. However, "
            "the shape is a trapezoid, not a rectangle. The label 'Rectangle1' is present"
        ),
    }


def test_critic_salvages_partial_json_passed_field():
    raw = '{"passed": false, "reasoning": "Only one shape is visible'

    result = critic._salvage_critic_reply(raw)

    assert result == {
        "passed": False,
        "reasoning": "Only one shape is visible",
    }
