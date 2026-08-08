from pathlib import Path
from unittest.mock import patch
import pytest
import yaml
from src.config.reader import load_config
from src.config.exceptions import (
    DimensionalMismatchError,
    InitialBoundsError,
    InvalidSchemaError,
)
from conftest import write_yaml


@pytest.mark.parametrize(
    "corrupted_block,key_to_replace",
    [
        ("global_limits", "metric_unrecognized"),
        ("state_bounds", "metric_unrecognized"),
        ("drift_rates", "metric_unrecognized"),
        ("volatilities", "metric_unrecognized"),
        ("initial_metrics", "metric_unrecognized"),
    ],
)
def test_invariant_metric_dimension(
    valid_config_dict: dict, tmp_path: Path, corrupted_block: str, key_to_replace: str
):
    """Asserts that any metric key not in top-level 'metrics' raises DimensionalMismatchError."""
    if corrupted_block == "global_limits":
        valid_config_dict["global_limits"][key_to_replace] = [0.0, 1.0]
    elif corrupted_block in ("state_bounds", "drift_rates", "volatilities"):
        state = valid_config_dict["global_behavior_states"][0]
        if corrupted_block == "state_bounds":
            state["state_bounds"][key_to_replace] = [0.0, 1.0]
        elif corrupted_block == "drift_rates":
            state["drift_rates"][key_to_replace] = 0.1
        elif corrupted_block == "volatilities":
            state["volatilities"][key_to_replace] = 0.1
    elif corrupted_block == "initial_metrics":
        valid_config_dict["entities"][0]["initial_metrics"][key_to_replace] = 5.0

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(DimensionalMismatchError):
        load_config(config_file)


def test_invariant_exact_metric_dimension_partial_keys_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies providing a subset of metrics fails exact dimensional alignment."""
    valid_config_dict["global_behavior_states"][0]["drift_rates"] = {"metric_1": 0.1}
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(DimensionalMismatchError, match="missing required metrics"):
        load_config(config_file)


def test_invariant_macro_shock_override_out_of_bounds_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies macro shock metric overrides exceeding bounds fail validation."""
    valid_config_dict["global_macro_shocks"][0]["instant_metric_overrides"]["metric_1"] = 999.0
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="lies outside"):
        load_config(config_file)


def test_invariant_coordinates_out_of_bounds_state(valid_config_dict: dict, tmp_path: Path):
    """Asserts initial_metrics outside of initial_state bounds raises InitialBoundsError."""
    valid_config_dict["entities"][0]["initial_metrics"]["metric_1"] = 50.0
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InitialBoundsError):
        load_config(config_file)


def test_invariant_coordinates_out_of_bounds_global(valid_config_dict: dict, tmp_path: Path):
    """Asserts initial_metrics outside of global_limits raises InitialBoundsError."""
    valid_config_dict["global_behavior_states"][0]["state_bounds"]["metric_1"] = [85.0, 200.0]
    valid_config_dict["entities"][0]["initial_metrics"]["metric_1"] = 150.0

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InitialBoundsError):
        load_config(config_file)


def test_invariant_entity_custom_state_drift_and_volatilities_validated(valid_config_dict: dict, tmp_path: Path):
    """Verifies custom states validate drift_rates and volatilities for key alignment."""
    valid_config_dict["toggles"]["use_global_behavior"] = False
    custom_state = {
        "name": "CUSTOM_STATE",
        "state_bounds": {"metric_1": [0.0, 100.0], "metric_2": [0.0, 10.0]},
        "drift_rates": {"metric_1": 0.5},
        "volatilities": {"metric_1": 0.1, "metric_2": 0.1},
        "boundary_stiffness": 0.5,
    }
    valid_config_dict["entities"][0]["behavior_states"] = [custom_state]
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(DimensionalMismatchError, match="missing required metrics"):
        load_config(config_file)


@pytest.mark.parametrize(
    "resolution, epoch, duration",
    [
        ("2d", "1d", "90d"),
        ("1d", "100d", "90d"),
        ("1w", "1d", "1d"),
    ],
)
def test_invariant_time_granularity_hierarchy_invalid_rejected(
    valid_config_dict: dict, tmp_path: Path, resolution: str, epoch: str, duration: str
):
    """Verifies configurations violating resolution <= epoch <= duration fail validation."""
    valid_config_dict["simulation"]["data_resolution"] = resolution
    valid_config_dict["simulation"]["epoch_interval"] = epoch
    valid_config_dict["simulation"]["duration"] = duration

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="Time hierarchy error"):
        load_config(config_file)


def test_guard_duplicate_metric_names(valid_config_dict: dict, tmp_path: Path):
    """Asserts that duplicate metric names in manifest raise InvalidSchemaError."""
    valid_config_dict["metrics"].append(
        {"name": "metric_1", "is_derivative": False, "primitive_type": "float"}
    )
    file_path = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError):
        load_config(file_path)


def test_guard_invalid_deferral_driver_metric(valid_config_dict: dict, tmp_path: Path):
    """Asserts that unknown driver_metric raises DimensionalMismatchError."""
    valid_config_dict["entities"][0]["deferral_policy"]["driver_metric"] = "non_existent_metric"
    file_path = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(DimensionalMismatchError):
        load_config(file_path)


def test_guard_invalid_macro_shock_target_state(valid_config_dict: dict, tmp_path: Path):
    """Asserts macro shock targeting an unlisted state raises InvalidSchemaError."""
    valid_config_dict["global_macro_shocks"][0]["target_state"] = "NON_EXISTENT_STATE"
    file_path = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError):
        load_config(file_path)


@pytest.mark.parametrize(
    "toggle_key,data_key",
    [
        ("use_global_behavior", "global_behavior_states"),
        ("use_global_macro_shock", "global_macro_shocks"),
        ("use_global_limits", "global_limits"),
    ],
)
def test_edge_case_toggle_enabled_data_missing(
    valid_config_dict: dict, tmp_path: Path, toggle_key: str, data_key: str
):
    """Asserts enabling global toggle with missing data structure raises InvalidSchemaError."""
    valid_config_dict["toggles"][toggle_key] = True
    valid_config_dict[data_key] = [] if isinstance(valid_config_dict[data_key], list) else {}

    file_path = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError):
        load_config(file_path)


def test_duplicate_entity_ids_raises_invalid_schema_error(valid_config_dict: dict, tmp_path: Path):
    """Verifies duplicate entity IDs trigger InvalidSchemaError."""
    valid_config_dict["entities"] = [
        {"id": "E001", "initial_state": "NOMINAL", "initial_metrics": {"temperature": 20.0}},
        {"id": "E001", "initial_state": "NOMINAL", "initial_metrics": {"temperature": 25.0}},
    ]

    config_file = tmp_path / "dup_id.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    with pytest.raises(InvalidSchemaError, match="Duplicate entity ID found"):
        load_config(config_file)


def test_missing_or_empty_entity_id_raises_invalid_schema_error(valid_config_dict: dict, tmp_path: Path):
    """Verifies empty string entity IDs trigger InvalidSchemaError."""
    valid_config_dict["entities"][0]["id"] = "   "

    config_file = tmp_path / "empty_id.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    with pytest.raises(InvalidSchemaError, match="cannot be empty or pure whitespace"):
        load_config(config_file)


def test_use_global_limits_false_disables_inheritance(valid_config_dict: dict, tmp_path: Path):
    """Verifies use_global_limits=False disables global bounds inheritance."""
    target_metric = valid_config_dict["metrics"][0]["name"]

    valid_config_dict["toggles"]["use_global_limits"] = False
    valid_config_dict["global_limits"] = {target_metric: [10.0, 95.0], "metric_2": [0.0, 10.0]}

    valid_config_dict["entities"][0]["initial_metrics"][target_metric] = 90.0
    valid_config_dict["entities"][0]["metric_bounds"] = None

    config_file = tmp_path / "global_limits_false.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    config = load_config(config_file)
    assert config is not None


def test_enable_state_engine_without_resolvable_states_raises_error(valid_config_dict: dict, tmp_path: Path):
    """Verifies state engine enabled without behavior states raises InvalidSchemaError."""
    valid_config_dict["toggles"]["enable_state_engine"] = True
    valid_config_dict["toggles"]["use_global_behavior"] = False
    valid_config_dict["global_behavior_states"] = []
    valid_config_dict["entities"][0]["behavior_states"] = None

    config_file = tmp_path / "no_states.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    with pytest.raises(InvalidSchemaError, match="resolves to no behavior states"):
        load_config(config_file)


def test_output_field_source_unknown_metric_raises_error(valid_config_dict: dict, tmp_path: Path):
    """Verifies output field referencing a non-existent metric raises InvalidSchemaError."""
    valid_config_dict["output"]["fields"].append({
        "name": "bad_column",
        "source": "metrics.non_existent_metric"
    })

    config_file = tmp_path / "bad_output_source.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    with pytest.raises(InvalidSchemaError, match="references non-existent metric"):
        load_config(config_file)


def test_guard_duplicate_global_state_names_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies duplicate state names in global_behavior_states raise InvalidSchemaError."""
    dup_state = valid_config_dict["global_behavior_states"][0].copy()
    valid_config_dict["global_behavior_states"].append(dup_state)
    file_path = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="Duplicate state name"):
        load_config(file_path)


def test_guard_duplicate_global_macro_shock_names_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies duplicate shock names in global_macro_shocks raise InvalidSchemaError."""
    dup_shock = valid_config_dict["global_macro_shocks"][0].copy()
    valid_config_dict["global_macro_shocks"].append(dup_shock)
    file_path = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="Duplicate macro shock name"):
        load_config(file_path)


def test_global_behavior_true_ignores_invalid_entity_custom_states(valid_config_dict: dict, tmp_path: Path):
    """Verifies use_global_behavior=True ignores entity custom state mismatch."""
    valid_config_dict["toggles"]["use_global_behavior"] = True
    valid_config_dict["entities"][0]["behavior_states"] = [{
        "name": "IGNORED_STATE",
        "state_bounds": {"metric_1": [0.0, 100.0]},
        "drift_rates": {"metric_1": 0.0},
        "volatilities": {"metric_1": 0.1},
        "boundary_stiffness": 0.5,
    }]

    config_file = write_yaml(valid_config_dict, tmp_path)
    config = load_config(config_file)
    assert config is not None


def test_disabled_state_engine_ignores_unlisted_initial_state(valid_config_dict: dict, tmp_path: Path):
    """Verifies enable_state_engine=False skips state presence validation."""
    valid_config_dict["toggles"]["enable_state_engine"] = False
    valid_config_dict["entities"][0]["initial_state"] = "NON_EXISTENT_STATE"

    config_file = write_yaml(valid_config_dict, tmp_path)
    config = load_config(config_file)
    assert config is not None


def test_output_field_source_invalid_engine_attribute_raises_error(valid_config_dict: dict, tmp_path: Path):
    """Verifies output field with an invalid engine attribute raises InvalidSchemaError."""
    valid_config_dict["output"]["fields"].append({
        "name": "bad_col",
        "source": "unrecognized_engine_attr"
    })

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="references unrecognized source"):
        load_config(config_file)

def test_output_field_header_duplicate_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies that duplicate field header names in output.fields trigger InvalidSchemaError."""
    valid_config_dict["output"]["fields"] = [
        {"name": "col_a", "source": "simulation_time"},
        {"name": "col_a", "source": "entity_id"},
    ]
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="Duplicate output field header name"):
        load_config(config_file)


def test_output_path_unwritable_directory_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies that an output path pointing to an unwritable directory raises InvalidSchemaError."""
    with patch("os.access", return_value=False):
        config_file = write_yaml(valid_config_dict, tmp_path)
        with pytest.raises(InvalidSchemaError, match="is not writable"):
            load_config(config_file)