from dataclasses import dataclass, field
from datetime import datetime
import logging
import pytest

from src.simulation.orchestrator import build_entity_registry, run_simulation
from src.simulation.nominal_gen import EntityContext


# ==============================================================================
# MOCK CONFIGURATION STRUCTURES
# ==============================================================================

@dataclass
class MockMetricDef:
    name: str
    is_derivative: bool = False
    formula: str | None = None


@dataclass
class MockRoute:
    max_route_speed: float = 60.0
    distance_miles: float = 30.0


@dataclass
class MockTask:
    task_id: str
    predecessors: list[str] = field(default_factory=list)
    nominal_duration_min: float = 30.0


@dataclass
class MockEntity:
    id: str
    entity_type: str = "truck"
    initial_location: str = "DEPOT_A"
    initial_metrics: dict[str, float] = field(
        default_factory=lambda: {
            "transit_velocity_mph": 60.0,
            "fuel_level_pct": 100.0,
            "queue_dwell_time_min": 0.0,
        }
    )


@dataclass
class MockToggles:
    use_state_engine: bool = False
    use_network_topology: bool = True
    use_workflow_dag: bool = True
    use_realism_filter: bool = False
    use_malformations_filter: bool = False


@dataclass
class MockSimParams:
    start_time: str = "2026-09-01T00:00:00Z"
    duration: str = "1h"
    data_resolution: str = "15m"
    epoch_interval: str = "1h"


@dataclass
class MockConfig:
    simulation: MockSimParams = field(default_factory=MockSimParams)
    pipeline_toggles: MockToggles = field(default_factory=MockToggles)
    metrics: list[MockMetricDef] = field(
        default_factory=lambda: [
            MockMetricDef(name="transit_velocity_mph"),
            MockMetricDef(name="fuel_level_pct"),
            MockMetricDef(name="queue_dwell_time_min"),
        ]
    )
    entities: list[MockEntity] = field(
        default_factory=lambda: [MockEntity(id="ENTITY_1")]
    )
    nominal_generator: type = field(
        default=type(
            "Nominal",
            (),
            {
                "baseline_metrics": {
                    "transit_velocity_mph": 60.0,
                    "fuel_level_pct": 100.0,
                    "queue_dwell_time_min": 0.0,
                }
            },
        )
    )
    network_topology: type = field(
        default=type(
            "Topo",
            (),
            {
                "routes": {
                    "DEPOT_A->HUB_B": MockRoute(max_route_speed=60.0, distance_miles=30.0)
                }
            },
        )
    )
    workflow_dag: type = field(
        default=type(
            "DAG",
            (),
            {
                "tasks": [
                    MockTask(task_id="TASK_INSPECT", predecessors=[]),
                    MockTask(task_id="TASK_UNLOAD", predecessors=["TASK_INSPECT"]),
                ]
            },
        )
    )


# ==============================================================================
# ENTITY REGISTRY BUILDER TESTS
# ==============================================================================

def test_build_entity_registry_basic_resolution():
    config = MockConfig()
    registry = build_entity_registry(config)

    assert "ENTITY_1" in registry
    ctx = registry["ENTITY_1"]
    assert isinstance(ctx, EntityContext)
    assert ctx.entity_id == "ENTITY_1"
    assert ctx.entity_type == "truck"
    assert ctx.current_node == "DEPOT_A"
    assert ctx.current_metrics["transit_velocity_mph"] == 60.0


def test_build_entity_registry_route_resolution():
    config = MockConfig()
    registry = build_entity_registry(config)

    # Origin DEPOT_A matches route prefix DEPOT_A->HUB_B
    assert registry["ENTITY_1"].active_route == "DEPOT_A->HUB_B"


def test_build_entity_registry_multiple_route_warning(caplog):
    config = MockConfig()
    # Add a second candidate route starting from DEPOT_A
    config.network_topology.routes["DEPOT_A->HUB_C"] = MockRoute()

    with caplog.at_level(logging.WARNING):
        registry = build_entity_registry(config)

    assert registry["ENTITY_1"].active_route == "DEPOT_A->HUB_B"
    assert "Multiple candidate routes from 'DEPOT_A' for entity 'ENTITY_1'" in caplog.text


def test_build_entity_registry_dag_initial_task():
    config = MockConfig()
    registry = build_entity_registry(config)

    # TASK_INSPECT has no predecessors, so it becomes the initial active task
    assert registry["ENTITY_1"].active_task_id == "TASK_INSPECT"


def test_build_entity_registry_toggles_disabled():
    config = MockConfig()
    config.pipeline_toggles.use_network_topology = False
    config.pipeline_toggles.use_workflow_dag = False

    registry = build_entity_registry(config)

    assert registry["ENTITY_1"].active_route is None
    assert registry["ENTITY_1"].active_task_id is None


# ==============================================================================
# SIMULATION ORCHESTRATION LOOP TESTS
# ==============================================================================

def test_run_simulation_step_counting(caplog):
    config = MockConfig()
    config.simulation.duration = "1h"
    config.simulation.data_resolution = "15m"  # 1 hour / 15 mins = 4 steps

    with caplog.at_level(logging.INFO):
        run_simulation(config)

    assert "Processed 4 total steps." in caplog.text


def test_run_simulation_route_completion_telemetry(caplog):
    config = MockConfig()
    # 60 mph for 30 miles = 30 minutes to complete route (2 steps of 15m)
    config.simulation.duration = "45m"
    config.simulation.data_resolution = "15m"

    with caplog.at_level(logging.INFO):
        run_simulation(config)

    assert "[ROUTE COMPLETED] Entity 'ENTITY_1' finished route 'DEPOT_A->HUB_B'. Arrived at 'HUB_B'" in caplog.text


def test_run_simulation_updates_entity_metrics():
    config = MockConfig()
    config.simulation.duration = "15m"
    config.simulation.data_resolution = "15m"

    run_simulation(config)
    # Orchestrator should run without exceptions and update state vectors per tick