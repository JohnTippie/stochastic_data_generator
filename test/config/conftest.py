from pathlib import Path
import typing
import pytest
import yaml

@pytest.fixture
def valid_config_dict(tmp_path: Path) -> dict[str, typing.Any]:
    """Returns a pristine, fully valid baseline configuration dictionary."""
    out_file = tmp_path / "outputs" / "test.csv"
    return {
        "meta": {
            "scenario_name": "test_scenario",
            "description": "Valid test scenario configuration",
            "seed": 42,
        },
        "simulation": {
            "start_time": "2026-01-01T00:00:00Z",
            "duration": "90d",
            "data_resolution": "1d",
            "epoch_interval": "1d",
        },
        "pipeline_toggles": {
            "use_state_engine": True,
            "use_network_topology": True,
            "use_resource_contention": False,
            "use_workflow_dag": False,
            "use_realism_filter": True,
            "use_malformations_filter": False,
        },
        "metrics": [
            {"name": "metric_1", "is_derivative": False, "primitive_type": "float"},
            {"name": "metric_2", "is_derivative": False, "primitive_type": "float"},
        ],
        "network_topology": {
            "routing_type": "stochastic_walk",
            "network_class": "linear",
            "nodes": ["DEPOT_A", "HUB_B"],
            "use_defined_routes": False,
            "adjacency_matrix": {
                "DEPOT_A": [{"destination": "HUB_B", "weight": 1.0}],
                "HUB_B": [{"destination": "DEPOT_A", "weight": 1.0}],
            },
        },
        "nominal_generator": {
            "baseline_metrics": {
                "metric_1": 95.0,
                "metric_2": 0.5,
            }
        },
        "state_engine": {
            "initial_state": "HEALTHY",
            "states": {
                "HEALTHY": {
                    "state_bounds": {
                        "metric_1": [85.0, 100.0],
                        "metric_2": [0.0, 1.0],
                    },
                    "drift_rates": {"metric_1": 0.1, "metric_2": -0.05},
                    "volatilities": {"metric_1": 0.5, "metric_2": 0.05},
                    "boundary_stiffness": 0.8,
                },
                "DEGRADED": {
                    "state_bounds": {
                        "metric_1": [0.0, 85.0],
                        "metric_2": [1.0, 10.0],
                    },
                    "drift_rates": {"metric_1": -1.0, "metric_2": 0.5},
                    "volatilities": {"metric_1": 2.0, "metric_2": 0.2},
                    "boundary_stiffness": 0.3,
                },
            },
            "transition_matrix": {
                "HEALTHY": {"HEALTHY": 0.9, "DEGRADED": 0.1},
                "DEGRADED": {"DEGRADED": 1.0},
            },
            "macro_shocks": [
                {
                    "name": "disaster",
                    "probability_per_epoch": 0.002,
                    "target_state": "DEGRADED",
                    "instant_metric_overrides": {"metric_1": 40.0, "metric_2": 5.0},
                }
            ],
        },
        "realism_filter": {
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
            "global_limits": {
                "metric_1": [0.0, 100.0],
                "metric_2": [0.0, 10.0],
            },
        },
        "entities": [
            {
                "id": "entity_001",
                "entity_type": "test_type",
                "initial_location": "DEPOT_A",
                "initial_state": "HEALTHY",
                "initial_metrics": {"metric_1": 95.0, "metric_2": 0.5},
            }
        ],
        "sink": {
            "format": "csv",
            "output_path": str(out_file),
            "metadata_toggles": {
                "include_state": True,
                "include_malformed_flag": False,
                "include_true_baseline": False,
            },
            "fields": [
                {"name": "time", "source": "system.timestamp"},
                {"name": "id", "source": "entity.id"},
                {"name": "m1", "source": "metrics.metric_1"},
            ],
        },
    }

def write_yaml(config_dict: dict[str, typing.Any], target_path: Path) -> Path:
    """Helper utility to write a config dictionary to disk as YAML."""
    file_path = target_path / "config.yaml"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f)
    return file_path