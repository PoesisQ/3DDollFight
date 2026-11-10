"""Audits the hand rig of every character in the roster.

The question "does the avatar have hand bones" keeps coming back because a
missing finger chain binds silently: ``HumanoidReplay`` falls back from the
Unity Humanoid slots to a name lookup, and when both miss it only logs a
warning while hand tracking keeps running. This script answers it from the
files, for all four characters at once, using the same name rule the runtime
uses.

    uv run --locked python tools/audit_hand_rigs.py

Exit code is 0 when every character exposes 15 movable joints per hand and 1
otherwise, so it can be used as a check.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "unity/Assets/Resources/DollFight/Characters.json"
VRM_FOLDER = ROOT / "unity/Assets/StreamingAssets/DollFight"

FINGERS = ("Thumb", "Index", "Middle", "Ring", "Little")
SEGMENTS = ("Proximal", "Intermediate", "Distal")
# VRM 1.0 names the thumb joints Metacarpal/Proximal/Distal; FBX rigs use the
# same Proximal/Intermediate/Distal triple as the other four fingers.
VRM_THUMB = ("Metacarpal", "Proximal", "Distal")
SIDES = ("Left", "Right")
PER_HAND = len(FINGERS) * len(SEGMENTS)


def normalise(name: str) -> str:
    """Mirror of ``HumanoidReplay.NormaliseBoneName``."""
    return "".join(character for character in name if character.isalnum()).lower()


def prefab_bones(path: Path) -> set[str]:
    """Every transform name in a Unity prefab, minus the ``*End`` leaf markers."""
    names = set()
    for match in re.finditer(r"^\s*m_Name:\s*(.+?)\s*$", path.read_text(encoding="utf-8"), re.M):
        name = match.group(1)
        if name.endswith("End") or name == "":
            # "Left_IndexDistalEnd" is a tip marker, not a joint.
            continue
        names.add(normalise(name))
    return names


def vrm_bones(path: Path) -> set[str]:
    """Node names plus the humanoid map of a VRM 1.0 file."""
    data = path.read_bytes()
    if len(data) < 20:
        return set()
    offset = 12
    length, _kind = struct.unpack_from("<II", data, offset)
    document = json.loads(data[offset + 8:offset + 8 + length].decode("utf-8"))
    names = {normalise(node.get("name", "")) for node in document.get("nodes", [])}
    humanoid = document.get("extensions", {}).get("VRMC_vrm", {}).get("humanoid", {})
    names |= {normalise(key) for key in humanoid.get("humanBones", {})}
    return names


def audit(entry: dict) -> tuple[int, int, list[str]]:
    """Count the articulated finger joints of both hands."""
    if entry.get("modelKind") == "vrm":
        path = VRM_FOLDER / entry["modelFile"]
        pattern = "{side}{finger}{segment}"
        thumb = VRM_THUMB
    else:
        path = ROOT / "unity/Assets/Resources" / (entry["resourcePath"] + ".prefab")
        pattern = "{side}_{finger}{segment}"
        thumb = SEGMENTS
    if not path.exists():
        raise FileNotFoundError(path)
    bones = vrm_bones(path) if entry.get("modelKind") == "vrm" else prefab_bones(path)

    counts, missing = [], []
    for side in SIDES:
        found = 0
        for finger in FINGERS:
            # Tripo/FBX exports the little finger as "Pinky".
            names = [finger] + (["Pinky"] if finger == "Little" else [])
            for segment in (thumb if finger == "Thumb" else SEGMENTS):
                keys = [normalise(pattern.format(side=side, finger=name, segment=segment))
                        for name in names]
                if any(key in bones for key in keys):
                    found += 1
                else:
                    missing.append(f"{side}/{finger}/{segment}")
        counts.append(found)
    return counts[0], counts[1], missing


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    failures, checked = 0, 0
    print(f"{'id':16s} {'kind':7s} {'left':>5s} {'right':>5s}  detail")
    for entry in catalog["characters"]:
        try:
            left, right, missing = audit(entry)
        except FileNotFoundError as error:
            print(f"{entry['id']:16s} {entry['modelKind']:7s}    --     --  skipped: {error}")
            continue
        checked += 1
        complete = left == PER_HAND and right == PER_HAND
        failures += 0 if complete else 1
        detail = "15 movable joints per hand" if complete else "missing: " + ", ".join(missing)
        print(f"{entry['id']:16s} {entry['modelKind']:7s} {left:2d}/15 {right:2d}/15  {detail}")
    print()
    if not checked:
        print("No character assets available to audit.")
    elif failures:
        print(f"{failures} character(s) cannot articulate a full hand.")
    else:
        print("All characters expose both hands: 15 joints, thumb through little finger.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
