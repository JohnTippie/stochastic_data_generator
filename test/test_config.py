from pathlib import Path
import typing
import pytest
import yaml
from pydantic import ValidationError

from src.config import (
    ConfigReader,
    SimulationConfig,
    ConfigError,
    ConfigNotFoundError,
    InvalidSchemaError,
    DimensionalMismatchError,
    InitialBoundsError,
)

# ================================================
# FIXTURES
# ================================================

@pytest.fixture
def valid_config_dict() -> dict[str, typing.Any]:
    """Returns a pristine, fully valid configuration dictionary."""
    return {
        "simulation": {
            "seed": "42",
            "start_time": "2026-01-01T00:00:00Z",
            "duration": "90d",
            "data_resolution": "1d",
            "epoch_interval": "1d",
        },
        "metrics": [
            {"name": "metric_1", "is_derivative": False, "primitive_type": "float"},
            {"name": "metric_2", "is_derivative": False, "primitive_type": "float"},
        ],
        "toggles": {
            "use_global_limits": True,
            "use_global_behavior": True,
            "use_global_macro_shock": True,
        },
        "global_limits": {
            "metric_1": [0.0, 100.0],
            "metric_2": [0.0, 10.0],
        },
        "global_behavior_states": [
            {
                "name": "HEALTHY",
                "state_bounds": {
                    "metric_1": [85.0, 100.0],
                    "metric_2": [0.0, 1.0],
                },
                "drift_rates": {"metric_1": 0.1, "metric_2": -0.05},
                "volatilities": {"metric_1": 0.5, "metric_2": 0.05},
                "boundary_stiffness": 0.8,
            },
            {
                "name": "DEGRADED",
                "state_bounds": {
                    "metric_1": [0.0, 85.0],
                    "metric_2": [1.0, 10.0],
                },
                "drift_rates": {"metric_1": -1.0, "metric_2": 0.5},
                "volatilities": {"metric_1": 2.0, "metric_2": 0.2},
                "boundary_stiffness": 0.3,
            },
        ],
        "global_macro_shocks": [
            {
                "name": "disaster",
                "probability_per_epoch": 0.002,
                "target_state": "DEGRADED",
                "instant_metric_overrides": {"metric_1": 40.0, "metric_2": 5.0},
            }
        ],
        "entities": [
            {
                "id": "entity_001",
                "entity_type": "test_type",
                "initial_state": "HEALTHY",
                "initial_metrics": {"metric_1": 95.0, "metric_2": 0.5},
                "deferral_policy": {
                    "enabled": True,
                    "driver_metric": "metric_1",
                    "max_drift_ttl_epochs": 3,
                    "base_probabilities": {
                        "fulfillment": 0.85,
                        "deferral": 0.10,
                        "cancellation": 0.05,
                    },
                    "aging_rules": {"cancel_escalation_per_epoch": 0.15},
                },
            }
        ],
        "output": {
            "format": "csv",
            "path": "outputs/test.csv",
            "fields": [
                {"name": "time", "source": "simulation_time"},
                {"name": "id", "source": "entity_id"},
            ],
            "metadata_toggles": {
                "include_state": True,
                "include_malformed_flag": False,
                "include_true_baseline": False,
            },
        },
    }

def write_yaml(config_dict: dict[str, typing.Any], target_path: Path) -> Path:
    """
    Helper utility to write a config dictionary to disk as YAML
    """
    file_path = target_path / "config.yaml"
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f)
    return file_path

# ================================================
# INVARIANT: IMMUTABILITY
# ================================================

def test_invariant_immutability(valid_config_dict: dict, tmp_path: Path):
    """
    Asserts that SimulationConfig and all child structures are frozen
    """
    config_file = write_yaml(valid_config_dict, tmp_path)
    config = ConfigReader.load_config(config_file)

    # Top-level / Metadata mutation
    with pytest.raises((ValidationError, TypeError)):
        config.simulation.seed = "999"

    # Nested entity attribute mutation attempt
    with pytest.raises((ValidationError, TypeError)):
        config.entities[0].initial_state = "DEGRADED"

    # Nested initial metrics dict key reassignment attempt
    with pytest.raises((ValidationError, TypeError)):
        config.entities[0].initial_metrics = {"metric_1": 10.0}

# ================================================
# INVARIANT: METRIC DIMENSION CONSISTENCY
# ================================================

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
    valid_config_dict: dict,
    tmp_path: Path,
    corrupted_block: str,
    key_to_replace: str
):

    """
    Asserts that any metric key not in top-level "metrics" raises DimensionalMismatchError
    """
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
        ConfigReader.load_config(config_file)

# ================================================
# INVARIANT: INITIAL COORDINATE VALIDITY
# ================================================

def test_invariant_coordinates_out_of_bounds_state(valid_config_dict: dict, tmp_path: Path):
    """
    Asserts that initial_metrics outside of initial_state bounds raies InitialBoundsError
    """
    valid_config_dict["entities"][0]["initial_metrics"]["metric_1"] = 50.0

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InitialBoundsError):
        ConfigReader.load_config(config_file)

def test_invariant_coordinates_out_of_bounds_global(valid_config_dict: dict, tmp_path: Path):
    """
    Asserts that initial_metrics outside of global_limits raises InitialBoundsError
    """

    valid_config_dict["global_behavior_states"][0]["state_bounds"]["metric_1"] = [85.0, 200.0]
    valid_config_dict["entities"][0]["initial_metrics"]["metric_1"] = 150.0

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InitialBoundsError):
        ConfigReader.load_config(config_file)

# ================================================
# INVARIANT: PROBABILITY CLAMPING
# ================================================

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
    valid_config_dict: dict,
    tmp_path: Path,
    bad_prob: float,
    field_path: tuple
):
    """
    Asserts that probabilites outside of [0.0,1.0] raise InvalidSchemaError or ValidationError
    """

    target = valid_config_dict
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = bad_prob

    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises((InvalidSchemaError, ConfigError, ValidationError)):
        ConfigReader.load_config(config_file)

# ================================================
# INVARIANT: TIME STRING FORMAT
# ================================================

@pytest.mark.parametrize("valid_time", ["10s", "30m", "12h", "90d", "2w"])

def test_invariant_valid_time_string(valid_config_dict: dict, tmp_path: Path, valid_time: str):
    """
    Verifies that correctly formatted time strings pass validation
    """
    valid_config_dict["simulation"]["duration"] = valid_time
    config_file = write_yaml(valid_config_dict, tmp_path)

    config = ConfigReader.load_config(config_file)
    assert config.simulation.duration == valid_time

@pytest.mark.parametrize("invalid_time", ["90days", "d90", "10.5d", "-5h", "100", "invalid"])
@pytest.mark.parametrize("field_name", ["duration", "data_resolution", "epoch_interval"])

def test_invariant_invalid_time_string(valid_config_dict: dict, tmp_path: Path, invalid_time: str, field_name: str):
    """
    Asserts that malformed time strings raise InvalidSchemaError
    """

    valid_config_dict["simulation"][field_name] = invalid_time
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises((InvalidSchemaError, ConfigError, ValidationError)):
        ConfigReader.load_config(config_file)

# ================================================
# HAPPY PATH
# ================================================

def test_happy_path_maximal_kitchen_sink_config(valid_config_dict: dict, tmp_path: Path):
    """
    Happy Path 1: Tests a fully loaded configuration where EVERY toggle, 
    override, state, shock, and metadata flag is populated and active.
    """
    # Add custom entity overrides to test full feature saturation
    valid_config_dict["entities"][0]["metric_bounds"] = {"metric_1": [0.0, 100.0], "metric_2": [0.0, 10.0]}
    valid_config_dict["entities"][0]["behavior_states"] = valid_config_dict["global_behavior_states"]
    valid_config_dict["entities"][0]["macro_shocks"] = valid_config_dict["global_macro_shocks"]
    
    file_path = write_yaml(valid_config_dict, tmp_path)
    config = ConfigReader.load_config(file_path)

    assert isinstance(config, SimulationConfig)
    assert config.toggles.enable_state_engine is True
    assert config.toggles.enable_realism_filter is True
    assert len(config.global_behavior_states) == 2
    assert len(config.global_macro_shocks) == 1
    assert config.entities[0].metric_bounds is not None


def test_happy_path_minimal_nominal_config(tmp_path: Path):
    """
    Happy Path 2: Tests a bare-bones configuration where state engines, 
    filters, and shocks are toggled off/empty for pure baseline schedule generation.
    """
    minimal_dict = {
        "simulation": {
            "seed": "1",
            "start_time": "2026-01-01T00:00:00Z",
            "duration": "1d",
            "data_resolution": "1h",
            "epoch_interval": "1h",
        },
        "metrics": [{"name": "primary_metric", "is_derivative": False, "primitive_type": "float"}],
        "toggles": {
            "enable_state_engine": False,
            "enable_realism_filter": False,
            "enable_malformations": False,
            "use_global_limits": False,
            "use_global_behavior": False,
            "use_global_macro_shock": False,
        },
        "global_limits": {},
        "global_behavior_states": [],
        "global_macro_shocks": [],
        "entities": [
            {
                "id": "bare_entity",
                "initial_state": "NOMINAL",
                "initial_metrics": {"primary_metric": 10.0},
                "deferral_policy": {
                    "enabled": False,
                    "max_drift_ttl_epochs": 1,
                    "base_probabilities": {"fulfillment": 1.0, "deferral": 0.0, "cancellation": 0.0},
                    "aging_rules": {"cancel_escalation_per_epoch": 0.0},
                },
            }
        ],
        "output": {
            "format": "csv",
            "path": "outputs/minimal.csv",
            "fields": [{"name": "val", "source": "metrics.primary_metric"}],
            "metadata_toggles": {
                "include_state": False,
                "include_malformed_flag": False,
                "include_true_baseline": False,
            },
        },
    }

    file_path = write_yaml(minimal_dict, tmp_path)
    config = ConfigReader.load_config(file_path)

    assert isinstance(config, SimulationConfig)
    assert config.toggles.enable_state_engine is False
    assert config.global_behavior_states == []
    assert config.global_macro_shocks == []

# ================================================
# EDGE CASES
# ================================================
def test_guard_empty_yaml(tmp_path: Path):
    """Asserts that empty or scalar YAML files raise InvalidSchemaError."""
    empty_file = tmp_path / "empty.yaml"
    empty_file.write_text("", encoding="utf-8")
    
    with pytest.raises(InvalidSchemaError):
        ConfigReader.load_config(empty_file)

def test_guard_duplicate_metric_names(valid_config_dict: dict, tmp_path: Path):
    """Asserts that duplicate metric names in manifest raise InvalidSchemaError."""
    valid_config_dict["metrics"].append(
        {"name": "metric_1", "is_derivative": False, "primitive_type": "float"}
    )
    file_path = write_yaml(valid_config_dict, tmp_path)
    
    with pytest.raises(InvalidSchemaError):
        ConfigReader.load_config(file_path)

def test_guard_invalid_deferral_driver_metric(valid_config_dict: dict, tmp_path: Path):
    """Asserts that unknown driver_metric raises DimensionalMismatchError."""
    valid_config_dict["entities"][0]["deferral_policy"]["driver_metric"] = "non_existent_metric"
    file_path = write_yaml(valid_config_dict, tmp_path)
    
    with pytest.raises(DimensionalMismatchError):
        ConfigReader.load_config(file_path)

def test_guard_invalid_macro_shock_target_state(valid_config_dict: dict, tmp_path: Path):
    """Asserts that macro shock targeting an unlisted state raises InvalidSchemaError."""
    valid_config_dict["global_macro_shocks"][0]["target_state"] = "NON_EXISTENT_STATE"
    file_path = write_yaml(valid_config_dict, tmp_path)
    
    with pytest.raises(InvalidSchemaError):
        ConfigReader.load_config(file_path)

def test_config_not_found_error(tmp_path: Path):
    """
    Edge Case Test: Asserts that passing a non-existent path 
    raises ConfigNotFoundError cleanly.
    """
    non_existent_file = tmp_path / "missing_config.yaml"

    with pytest.raises(ConfigNotFoundError):
        ConfigReader.load_config(non_existent_file)

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
    """
    Edge Case: Asserts that enabling a global toggle while leaving the corresponding 
    data structure empty or missing raises an explicit InvalidSchemaError.
    """
    valid_config_dict["toggles"][toggle_key] = True
    valid_config_dict[data_key] = [] if isinstance(valid_config_dict[data_key], list) else {}

    file_path = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError):
        ConfigReader.load_config(file_path)

def test_duplicate_entity_ids_raises_invalid_schema_error(valid_config_dict, tmp_path):
    """Verifies that duplicate entity IDs trigger an InvalidSchemaError."""
    valid_config_dict["entities"] = [
        {"id": "E001", "initial_state": "NOMINAL", "initial_metrics": {"temperature": 20.0}},
        {"id": "E001", "initial_state": "NOMINAL", "initial_metrics": {"temperature": 25.0}},
    ]
    
    config_file = tmp_path / "dup_id.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    with pytest.raises(InvalidSchemaError, match="Duplicate entity ID found"):
        ConfigReader.load_config(config_file)


def test_missing_or_empty_entity_id_raises_invalid_schema_error(valid_config_dict, tmp_path):
    """Verifies that empty string entity IDs trigger an InvalidSchemaError."""
    valid_config_dict["entities"][0]["id"] = "   "
    
    config_file = tmp_path / "empty_id.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    with pytest.raises(InvalidSchemaError, match="empty or missing 'id'"):
        ConfigReader.load_config(config_file)

def test_use_global_limits_false_disables_inheritance(valid_config_dict, tmp_path):
    """
    Verifies Model B logic: when use_global_limits is False and entity bounds are None,
    no limits apply, allowing metric values outside global limits to pass without error.
    """
    # 1. Grab a valid metric name defined in the base test fixture
    target_metric = valid_config_dict["metrics"][0]["name"]

    # 2. Configure global limit on that valid metric
    valid_config_dict["toggles"]["use_global_limits"] = False
    valid_config_dict["global_limits"] = {target_metric: [95.0, 10.0]}
    
    # 3. Set entity value to 50.0 (outside [0, 10]) with entity bounds set to None
    valid_config_dict["entities"][0]["initial_metrics"] = {target_metric: 90.0}
    valid_config_dict["entities"][0]["metric_bounds"] = None

    config_file = tmp_path / "global_limits_false.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    # 4. Must pass cleanly because use_global_limits=False disables bound checking
    config = ConfigReader.load_config(config_file)
    assert config is not None

def test_enable_state_engine_without_resolvable_states_raises_error(valid_config_dict, tmp_path):
    """
    Verifies that enabling state engine when an entity has no behavior states
    and global behavior is toggled off raises an InvalidSchemaError.
    """
    valid_config_dict["toggles"]["enable_state_engine"] = True
    valid_config_dict["toggles"]["use_global_behavior"] = False
    valid_config_dict["global_behavior_states"] = []
    valid_config_dict["entities"][0]["behavior_states"] = None

    config_file = tmp_path / "no_states.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    with pytest.raises(InvalidSchemaError, match="resolves to no behavior states"):
        ConfigReader.load_config(config_file)

def test_output_field_source_unknown_metric_raises_error(valid_config_dict, tmp_path):
    """Verifies that an output field referencing a non-existent metric raises InvalidSchemaError."""
    valid_config_dict["output"]["fields"].append({
        "name": "bad_column",
        "source": "metrics.non_existent_metric"
    })

    config_file = tmp_path / "bad_output_source.yaml"
    config_file.write_text(yaml.dump(valid_config_dict))

    with pytest.raises(InvalidSchemaError, match="references non-existent metric"):
        ConfigReader.load_config(config_file)

def test_extra_forbid_rejects_unknown_top_level_and_nested_keys(valid_config_dict, tmp_path):
    """Verifies Pydantic extra='forbid' policy on top-level and nested structures."""
    # 1. Top-Level Unknown Key
    bad_root_dict = valid_config_dict.copy()
    bad_root_dict["bogus_root_key"] = "unauthorized_data"
    
    file_root = tmp_path / "bad_root.yaml"
    file_root.write_text(yaml.dump(bad_root_dict))
    
    with pytest.raises(InvalidSchemaError):
        ConfigReader.load_config(file_root)

    # 2. Nested Unknown Key inside Entity
    bad_nested_dict = valid_config_dict.copy()
    bad_nested_dict["entities"][0]["bogus_entity_key"] = 999
    
    file_nested = tmp_path / "bad_nested.yaml"
    file_nested.write_text(yaml.dump(bad_nested_dict))

    with pytest.raises(InvalidSchemaError):
        ConfigReader.load_config(file_nested)

def test_shipped_reference_config_yaml_is_valid():
    """
    Guarantees that the repository's root config.yaml remains in sync with 
    the schema definitions as the codebase evolves.
    """
    reference_config_path = Path("config.yaml")
    assert reference_config_path.exists(), "Root config.yaml was not found in repo root!"

    # Must load cleanly without raising any Schema or Validation errors
    config = ConfigReader.load_config(reference_config_path)
    
    assert config is not None
    assert len(config.entities) > 0
    assert len(config.metrics) > 0