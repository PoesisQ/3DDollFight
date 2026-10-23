import json
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from dollfight.contracts import validate_message

FIXTURES = Path(__file__).parent / "fixtures"


def load(kind):
    return json.loads((FIXTURES / f"{kind}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind", ["pose_frame", "action_event"])
def test_draft_schema_and_synthetic_message(kind):
    schema = files("dollfight").joinpath("schemas", f"{kind}.schema.json")
    Draft202012Validator.check_schema(json.loads(schema.read_text(encoding="utf-8")))
    validate_message(load(kind))


def test_missing_joint_is_not_allowed_to_be_an_origin_measurement():
    message = load("pose_frame")
    message["joints"]["right_toe"]["position_m"] = [0, 0, 0]
    with pytest.raises((ValueError, ValidationError)):
        validate_message(message)


def test_nonfinite_numbers_are_rejected_even_if_python_accepts_json_nan():
    message = load("pose_frame")
    message["joints"]["head"]["position_m"][0] = float("nan")
    with pytest.raises(ValueError):
        validate_message(message)


def test_unknown_joint_name_is_rejected():
    message = load("pose_frame")
    message["joints"]["left_hand"] = message["joints"].pop("left_wrist")
    with pytest.raises((ValueError, ValidationError)):
        validate_message(message)


def test_numeric_nanoseconds_are_rejected_to_preserve_javascript_precision():
    message = load("pose_frame")
    message["captured_at_ns"] = 1234567890123456789
    with pytest.raises(ValidationError):
        validate_message(message)


def test_action_time_cannot_run_backwards():
    message = load("action_event")
    message["committed_at_ns"] = "999999999"
    with pytest.raises(ValueError):
        validate_message(message)


def test_recognition_proposal_does_not_decide_damage():
    message = load("action_event")
    message["damage"] = 100
    with pytest.raises(ValidationError):
        validate_message(message)
