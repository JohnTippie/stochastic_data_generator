from pathlib import Path
import pytest
import yaml
from typing import Any
from pydantic import ValidationError
from src.config.reader import load_config
from src.config.exceptions import ConfigError, InvalidSchemaError
from conftest import write_yaml


def test_invariant_immutability(valid_config_dict: dict, tmp_path: Path):
    """Asserts that SimulationConfig and all child structures are frozen."""
    config_file = write_yaml(valid_config_dict, tmp_path)
    config = load_config(config_file)

    with pytest.raises((ValidationError, TypeError)):
        config.simulation.seed = "999"

    with pytest.raises((ValidationError, TypeError)):
        config.entities[0].initial_state = "DEGRADED"

    with pytest.raises((ValidationError, TypeError)):
        config.entities[0].initial_metrics = {"metric_1": 10.0}


def test_invariant_true_container_immutability(valid_config_dict: dict, tmp_path: Path):
    """Asserts true container immutability across models, sequences, and mappings."""
    config_file = write_yaml(valid_config_dict, tmp_path)
    config = load_config(config_file)

    with pytest.raises((ValidationError, AttributeError, TypeError)):
        config.simulation.seed = "999"

    with pytest.raises(AttributeError):
        config.entities.append(config.entities[0])

    with pytest.raises(TypeError):
        config.entities[0].initial_metrics["metric_1"] = 999.0

    if config.global_limits:
        with pytest.raises(TypeError):
            config.global_limits["metric_1"] = (0.0, 999.0)


@pytest.mark.parametrize(
    "corrupted_block",
    ["global_limits", "state_bounds", "metric_bounds"],
)
def test_invariant_bounding_geometry_min_gt_max_rejected(
    valid_config_dict: dict, tmp_path: Path, corrupted_block: str
):
    """Verifies that inverted bounding regions where min > max fail schema validation."""
    if corrupted_block == "global_limits":
        valid_config_dict["global_limits"]["metric_1"] = [100.0, 0.0]
    elif corrupted_block == "state_bounds":
        valid_config_dict["global_behavior_states"][0]["state_bounds"]["metric_1"] = [100.0, 0.0]
    elif corrupted_block == "metric_bounds":
        valid_config_dict["entities"][0]["metric_bounds"] = {
            "metric_1": [100.0, 0.0],
            "metric_2": [0.0, 10.0],
        }

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="less than or equal to upper bound"):
        load_config(config_file)


@pytest.mark.parametrize("bad_prob", [-0.1, 1.05, 2.0])
@pytest.mark.parametrize(
    "field_path",
    [
        ("global_behavior_states", 0, "boundary_stiffness"),
        ("global_macro_shocks", 0, "probability_per_epoch"),
        ("entities", 0, "deferral_policy", "base_probabilities", "fulfillment"),
        ("entities", 0, "deferral_policy", "base_probabilities", "deferral"),
        ("entities", 0, "deferral_policy", "base_probabilities", "cancellation"),
    ],
)
def test_invariant_probability_clamping(
    valid_config_dict: dict, tmp_path: Path, bad_prob: float, field_path: tuple
):
    """Asserts that probabilities outside of [0.0, 1.0] raise InvalidSchemaError or ValidationError."""
    target = valid_config_dict
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = bad_prob

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises((InvalidSchemaError, ConfigError, ValidationError)):
        load_config(config_file)


@pytest.mark.parametrize(
    "p_ful, p_def, p_can",
    [
        (0.8, 0.8, 0.8),
        (0.5, 0.2, 0.1),
        (0.0, 0.0, 0.0),
    ],
)
def test_invariant_deferral_probabilities_simplex_enforced(
    valid_config_dict: dict, tmp_path: Path, p_ful: float, p_def: float, p_can: float
):
    """Verifies that deferral base probabilities that do not sum to 1.0 fail schema validation."""
    policy = valid_config_dict["entities"][0]["deferral_policy"]["base_probabilities"]
    policy["fulfillment"] = p_ful
    policy["deferral"] = p_def
    policy["cancellation"] = p_can

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="must sum to 1.0"):
        load_config(config_file)


@pytest.mark.parametrize("invalid_stiffness", [0.0, -0.1, 1.05])
def test_invariant_boundary_stiffness_strictly_positive(
    valid_config_dict: dict, tmp_path: Path, invalid_stiffness: float
):
    """Verifies that boundary_stiffness <= 0.0 or > 1.0 fails schema validation."""
    valid_config_dict["global_behavior_states"][0]["boundary_stiffness"] = invalid_stiffness
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises((InvalidSchemaError, ConfigError, ValidationError)):
        load_config(config_file)


@pytest.mark.parametrize("valid_time", ["10s", "30m", "12h", "90d", "2w"])
def test_invariant_valid_time_string(valid_config_dict: dict, tmp_path: Path, valid_time: str):
    """Verifies that correctly formatted time strings pass validation."""
    valid_config_dict["simulation"]["duration"] = valid_time
    valid_config_dict["simulation"]["epoch_interval"] = valid_time
    valid_config_dict["simulation"]["data_resolution"] = valid_time

    config_file = write_yaml(valid_config_dict, tmp_path)

    config = load_config(config_file)
    assert config.simulation.duration == valid_time


@pytest.mark.parametrize("invalid_time", ["90days", "d90", "10.5d", "-5h", "100", "invalid"])
@pytest.mark.parametrize("field_name", ["duration", "data_resolution", "epoch_interval"])
def test_invariant_invalid_time_string(
    valid_config_dict: dict, tmp_path: Path, invalid_time: str, field_name: str
):
    """Asserts that malformed time strings raise InvalidSchemaError."""
    valid_config_dict["simulation"][field_name] = invalid_time
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises((InvalidSchemaError, ConfigError, ValidationError)):
        load_config(config_file)


def test_extra_forbid_rejects_unknown_top_level_and_nested_keys(valid_config_dict: dict, tmp_path: Path):
    """Verifies Pydantic extra='forbid' policy on top-level and nested structures."""
    bad_root_dict = valid_config_dict.copy()
    bad_root_dict["bogus_root_key"] = "unauthorized_data"

    file_root = tmp_path / "bad_root.yaml"
    file_root.write_text(yaml.dump(bad_root_dict))

    with pytest.raises(InvalidSchemaError):
        load_config(file_root)

    bad_nested_dict = valid_config_dict.copy()
    bad_nested_dict["entities"][0]["bogus_entity_key"] = 999

    file_nested = tmp_path / "bad_nested.yaml"
    file_nested.write_text(yaml.dump(bad_nested_dict))

    with pytest.raises(InvalidSchemaError):
        load_config(file_nested)

@pytest.mark.parametrize("non_finite_val", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    "corrupted_block",
    ["global_limits", "drift_rates", "initial_metrics", "deferral_prob"],
)
def test_invariant_non_finite_floats_rejected(
    valid_config_dict: dict,
    tmp_path: Path,
    non_finite_val: float,
    corrupted_block: str,
):
    """
    Verifies that NaN, Infinity, and -Infinity are rejected across all numeric fields.
    """
    if corrupted_block == "global_limits":
        valid_config_dict["global_limits"]["metric_1"] = [0.0, non_finite_val]
    elif corrupted_block == "drift_rates":
        valid_config_dict["global_behavior_states"][0]["drift_rates"]["metric_1"] = non_finite_val
    elif corrupted_block == "initial_metrics":
        valid_config_dict["entities"][0]["initial_metrics"]["metric_1"] = non_finite_val
    elif corrupted_block == "deferral_prob":
        valid_config_dict["entities"][0]["deferral_policy"]["base_probabilities"]["fulfillment"] = non_finite_val

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError):
        load_config(config_file)

@pytest.mark.parametrize("invalid_id", ["", "   ", " metric_1", "metric_1 ", "\tmetric_1\n"])
@pytest.mark.parametrize("target_field", ["metric_name", "entity_id"])
def test_invariant_string_identifier_sanitation_rejected(
    valid_config_dict: dict,
    tmp_path: Path,
    invalid_id: str,
    target_field: str,
):
    """
    Verifies that empty strings, pure whitespace, and leading/trailing whitespace
    are rejected on metric names and entity IDs.
    """
    if target_field == "metric_name":
        valid_config_dict["metrics"][0]["name"] = invalid_id
    elif target_field == "entity_id":
        valid_config_dict["entities"][0]["id"] = invalid_id

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError):
        load_config(config_file)

@pytest.mark.parametrize("invalid_ts", ["not-a-datetime", "2026-99-99T00:00:00Z", "01/01/2026", "2026-01-01T25:00:00Z"])
def test_invariant_iso8601_timestamp_invalid_rejected(valid_config_dict: dict, tmp_path: Path, invalid_ts: str):
    """Verifies that malformed ISO-8601 timestamps fail schema validation."""
    valid_config_dict["simulation"]["start_time"] = invalid_ts
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError):
        load_config(config_file)


@pytest.mark.parametrize("invalid_seed", ["-1", "-100", "not_a_number", 3.14])
def test_invariant_numpy_seed_invalid_rejected(valid_config_dict: dict, tmp_path: Path, invalid_seed: Any):
    """Verifies that seeds failing NumPy SeedSequence validation raise InvalidSchemaError."""
    valid_config_dict["simulation"]["seed"] = invalid_seed
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError):
        load_config(config_file)