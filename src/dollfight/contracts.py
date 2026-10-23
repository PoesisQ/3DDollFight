"""Validate draft wire messages without depending on a camera or an engine."""

import json
import math
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

JOINTS = (
    "pelvis",
    "spine",
    "chest",
    "neck",
    "head",
    "left_shoulder",
    "left_elbow",
    "left_wrist",
    "right_shoulder",
    "right_elbow",
    "right_wrist",
    "left_hip",
    "left_knee",
    "left_ankle",
    "left_toe",
    "right_hip",
    "right_knee",
    "right_ankle",
    "right_toe",
)


def _require_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN and Infinity are not valid protocol numbers")
    if isinstance(value, dict):
        for item in value.values():
            _require_finite(item)
    elif isinstance(value, list):
        for item in value:
            _require_finite(item)


def validate_message(message: dict[str, Any]) -> None:
    """Validate shape and semantics; raise ValueError/ValidationError on failure.

    Sequence order and event de-duplication are receiver state, outside this
    stateless check. Nanosecond timestamps are decimal strings for JS clients.
    """
    kind = message.get("message_type")
    if kind not in ("pose_frame", "action_event"):
        raise ValueError(f"Unsupported message_type: {kind!r}")
    _require_finite(message)
    resource = files("dollfight").joinpath("schemas", f"{kind}.schema.json")
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(message)
    if kind == "pose_frame":
        if set(message["joints"]) != set(JOINTS):
            raise ValueError("canonical19 requires exactly the documented joints")
        for name, joint in message["joints"].items():
            missing = joint["tracking_state"] == "missing"
            if missing != (joint["position_m"] is None):
                raise ValueError(f"{name}: missing joints must have null positions")
            if missing and joint["confidence"] != 0:
                raise ValueError(f"{name}: missing joints must have zero confidence")
    else:
        if int(message["started_at_ns"]) > int(message["committed_at_ns"]):
            raise ValueError("An action cannot commit before it starts")
