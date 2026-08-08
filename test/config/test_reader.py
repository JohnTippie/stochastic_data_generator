from pathlib import Path
from src.config.reader import load_config, ConfigReader
from src.config.schemas import SimulationConfig
from conftest import write_yaml


def test_happy_path_maximal_kitchen_sink_config(valid_config_dict: dict, tmp_path: Path):
    """Happy Path: Tests fully loaded configuration with active overrides."""
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
    """Happy Path: Tests bare-bones configuration without state engines or shocks."""
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
    assert config.global_behavior_states == ()
    assert config.global_macro_shocks == ()


def test_shipped_reference_config_yaml_is_valid():
    """Guarantees repository root config.yaml loads cleanly."""
    reference_config_path = Path("config.yaml")
    assert reference_config_path.exists(), "Root config.yaml was not found in repo root!"

    config = ConfigReader.load_config(reference_config_path)

    assert config is not None
    assert len(config.entities) > 0
    assert len(config.metrics) > 0


def test_functional_top_level_load_config_import(valid_config_dict: dict, tmp_path: Path):
    """Verifies load_config can be invoked directly as a top-level function."""
    file_path = write_yaml(valid_config_dict, tmp_path)
    config = load_config(file_path)

    assert isinstance(config, SimulationConfig)
    assert len(config.entities) > 0