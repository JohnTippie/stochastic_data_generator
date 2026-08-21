import copy
from pathlib import Path
from unittest.mock import patch
import pytest

from src.config.exceptions import (
    DimensionalMismatchError,
    InitialBoundsError,
    InvalidSchemaError,
)
from src.config.invariants import validate_domain_invariants
from src.config.schemas import SimulationConfig

# ==============================================================================
# PIPELINE TOGGLE ALIGNMENT
# ==============================================================================

def test_toggle_enabled_but_section_missing_raises_error(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    raw_dict["pipeline_toggles"]["use_state_engine"] = True
    raw_dict["state_engine"] = None  # Toggle is True, but data is None
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InvalidSchemaError, match="Pipeline toggle 'state_engine' is set to True"):
        validate_domain_invariants(config)

# ==============================================================================
# METRIC & ENTITY UNIQUENESS
# ==============================================================================

def test_duplicate_metric_names_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    raw_dict["metrics"].append(
        {"name": "metric_1", "is_derivative": False, "primitive_type": "float"}
    )
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InvalidSchemaError, match="Duplicate metric name 'metric_1'"):
        validate_domain_invariants(config)

def test_duplicate_entity_ids_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    dup_entity = copy.deepcopy(raw_dict["entities"][0])
    raw_dict["entities"].append(dup_entity)
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InvalidSchemaError, match="Duplicate entity ID 'entity_001'"):
        validate_domain_invariants(config)

# ==============================================================================
# TIME HIERARCHY
# ==============================================================================

@pytest.mark.parametrize(
    "resolution, epoch, duration",
    [
        ("2h", "1h", "30d"),  # resolution > epoch
        ("1m", "2d", "1d"),   # epoch > duration
    ],
)
def test_time_hierarchy_violations_rejected(
    valid_config_dict: dict,
    resolution: str,
    epoch: str,
    duration: str,
):
    raw_dict = copy.deepcopy(valid_config_dict)
    raw_dict["simulation"]["data_resolution"] = resolution
    raw_dict["simulation"]["epoch_interval"] = epoch
    raw_dict["simulation"]["duration"] = duration
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InvalidSchemaError, match="Time hierarchy error"):
        validate_domain_invariants(config)

# ==============================================================================
# DIMENSIONAL ALIGNMENT
# ==============================================================================

def test_baseline_metrics_missing_metric_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    del raw_dict["nominal_generator"]["baseline_metrics"]["metric_2"]
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(DimensionalMismatchError, match="missing required metrics"):
        validate_domain_invariants(config)

def test_deferral_driver_metric_not_in_manifest_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    raw_dict["realism_filter"]["deferral_policy"]["driver_metric"] = "non_existent"
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(DimensionalMismatchError, match="driver_metric 'non_existent' is not declared"):
        validate_domain_invariants(config)

# ==============================================================================
# TOPOLOGY INTEGRITY
# ==============================================================================

def test_route_referencing_undeclared_node_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    raw_dict["network_topology"]["use_defined_routes"] = True
    raw_dict["network_topology"]["routes"] = {
        "DEPOT_A->UNDECLARED_NODE": {
            "distance_miles": 10.0,
            "nominal_travel_time_min": 15,
            "max_throughput_capacity": 100,
            "max_route_speed": 65,
        }
    }
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InvalidSchemaError, match="references undeclared node"):
        validate_domain_invariants(config)

# ==============================================================================
# WORKFLOW DAG & RESOURCE POOLS
# ==============================================================================

def test_task_referencing_undeclared_resource_pool_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    raw_dict["pipeline_toggles"]["use_workflow_dag"] = True
    raw_dict["pipeline_toggles"]["use_resource_contention"] = True
    raw_dict["resource_pools"] = [
        {
            "id": "DOCK_1",
            "total_capacity": 2,
            "queue_policy": "FIFO",
            "queue_contention_penalty_min": 10.0,
        }
    ]
    raw_dict["workflow_dag"] = {
        "tasks": [
            {
                "task_id": "TASK_1",
                "nominal_duration_min": 10,
                "predecessors": [],
                "required_resource_pool": "NON_EXISTENT_POOL",
            }
        ]
    }
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InvalidSchemaError, match="references undeclared resource pool"):
        validate_domain_invariants(config)

def test_workflow_dag_cycle_detection_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    raw_dict["pipeline_toggles"]["use_workflow_dag"] = True
    raw_dict["workflow_dag"] = {
        "tasks": [
            {
                "task_id": "TASK_1",
                "nominal_duration_min": 10,
                "predecessors": ["TASK_2"],
            },
            {
                "task_id": "TASK_2",
                "nominal_duration_min": 20,
                "predecessors": ["TASK_1"],
            },
        ]
    }
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InvalidSchemaError, match="Circular dependency detected in workflow DAG"):
        validate_domain_invariants(config)

# ==============================================================================
# STATE ENGINE INTEGRITY
# ==============================================================================

def test_macro_shock_override_violates_global_limits_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    # Global limit for metric_1 is [0.0, 100.0]; set override to 200.0
    raw_dict["state_engine"]["macro_shocks"][0]["instant_metric_overrides"]["metric_1"] = 200.0
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InitialBoundsError, match="violates global limits"):
        validate_domain_invariants(config)

# ==============================================================================
# INITIAL COORDINATES
# ==============================================================================

def test_entity_initial_metric_outside_state_bounds_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    # HEALTHY state bounds for metric_1 are [85.0, 100.0]; set initial metric to 10.0
    raw_dict["entities"][0]["initial_metrics"]["metric_1"] = 10.0
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InitialBoundsError, match="lies outside initial state"):
        validate_domain_invariants(config)

# ==============================================================================
# SINK & OUTPUT PATH
# ==============================================================================

def test_sink_field_referencing_invalid_namespace_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    raw_dict["sink"]["fields"].append(
        {"name": "invalid_col", "source": "unsupported_namespace.metric"}
    )
    config = SimulationConfig.model_validate(raw_dict)

    with pytest.raises(InvalidSchemaError, match="invalid source namespace"):
        validate_domain_invariants(config)

def test_unwritable_output_path_rejected(valid_config_dict: dict):
    raw_dict = copy.deepcopy(valid_config_dict)
    config = SimulationConfig.model_validate(raw_dict)

    with patch("os.access", return_value=False):
        with pytest.raises(InvalidSchemaError, match="is not writable"):
            validate_domain_invariants(config)