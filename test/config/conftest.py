from pathlib import Path
import typing
import pytest
import yaml


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
    """Helper utility to write a config dictionary to disk as YAML."""
    file_path = target_path / "config.yaml"
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f)
    return file_path