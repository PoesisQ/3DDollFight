"""Every character in the roster must expose a full hand to the retargeter.

The retargeter falls back from Unity's Humanoid finger slots to a name lookup,
and when both miss it only logs a warning: hand tracking keeps running and the
fingers simply never move. That failure is invisible in the data files and only
shows up as "the avatar has no hand bones" several rounds later, so it is
checked here for all four characters rather than just the one the default match
loads.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "unity/Assets/Resources/DollFight/Characters.json"


@pytest.mark.skipif(not CATALOG.exists(), reason="Unity character catalog not present")
def test_every_character_has_fifteen_joints_per_hand():
    result = subprocess.run([sys.executable, str(ROOT / "tools/audit_hand_rigs.py")],
                            capture_output=True, text=True, check=False)
    output = result.stdout + result.stderr
    if "skipped:" in output or "No character assets available" in output:
        pytest.skip("character assets are not available in this checkout")
    assert result.returncode == 0, output
    assert output.count("/15") >= 8, output          # four characters, two hands
    assert "All characters expose both hands" in output, output
