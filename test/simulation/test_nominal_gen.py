from dataclasses import dataclass, field, FrozenInstanceError
from datetime import datetime, timedelta
import pytest

from src.simulation.nominal_gen import (
    EntityContext,
    NominalGenerator,
    NominalStateVector,
    SafeFormulaEvaluator,
)

# ==============================================================================
# MOCK CONFIG STRUCTURES FOR ISOLATED UNIT TESTING
# ==============================================================================

@dataclass
class MockMetricDef:
    name: str
    is_derivative: bool = False
    formula: str | None = None

@dataclass
class MockRoute:
    max_route_speed: float = 65.0
    distance_miles: float = 100.0

@dataclass
class MockTask:
    task_id: str
    nominal_duration_min: float = 30.0

@dataclass
class MockEntity:
    id: str
    entity_type: str = "truck"
    initial_location: str = "DEPOT_A"
    initial_metrics: dict[str, float] | None = None

@dataclass
class MockConfig:
    metrics: list[MockMetricDef] = field(default_factory=list)
    entities: list[MockEntity] = field(default_factory=list)
    pipeline_toggles: type = field(default=type("Toggles", (), {
        "use_network_topology": True,
        "use_workflow_dag": True
    }))
    nominal_generator: type = field(default=type("Nominal", (), {
        "baseline_metrics": {
            "transit_velocity_mph": 60.0,
            "fuel_level_pct": 100.0,
            "queue_dwell_time_min": 10.0,
            "equipment_wear_index": 0.1
        }
    }))
    network_topology: type = field(default=type("Topo", (), {
        "routes": {"DEPOT_A->HUB_B": MockRoute(max_route_speed=60.0, distance_miles=30.0)}
    }))
    workflow_dag: type = field(default=type("DAG", (), {
        "tasks": [MockTask(task_id="TASK_INSPECT", nominal_duration_min=15.0)]
    }))


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def mock_config() -> MockConfig:
    return MockConfig(
        metrics=[
            MockMetricDef(name="transit_velocity_mph"),
            MockMetricDef(name="fuel_level_pct"),
            MockMetricDef(name="queue_dwell_time_min"),
            MockMetricDef(name="equipment_wear_index"),
            MockMetricDef(
                name="fuel_burn_rate",
                is_derivative=True,
                formula="(100.0 - fuel_level_pct) / clamp(transit_velocity_mph, 1.0, 120.0)"
            ),
        ],
        entities=[
            MockEntity(id="ENTITY_DEFAULT"),
            MockEntity(
                id="ENTITY_OVERRIDE",
                initial_metrics={
                    "transit_velocity_mph": 50.0,
                    "fuel_level_pct": 80.0,
                    "queue_dwell_time_min": 5.0,
                    "equipment_wear_index": 0.2
                }
            )
        ]
    )


# ==============================================================================
# AST FORMULA EVALUATOR TESTS
# ==============================================================================

def test_ast_evaluator_basic_arithmetic():
    variables = {"a": 10.0, "b": 2.0}
    evaluator = SafeFormulaEvaluator(variables)
    
    assert evaluator.evaluate("a + b") == 12.0
    assert evaluator.evaluate("a - b") == 8.0
    assert evaluator.evaluate("a * b") == 20.0
    assert evaluator.evaluate("a / b") == 5.0
    assert evaluator.evaluate("a ** b") == 100.0

def test_ast_evaluator_allowed_functions():
    variables = {"val": -15.5, "speed": 150.0}
    evaluator = SafeFormulaEvaluator(variables)
    
    assert evaluator.evaluate("abs(val)") == 15.5
    assert evaluator.evaluate("min(10, 20)") == 10.0
    assert evaluator.evaluate("max(10, 20)") == 20.0
    assert evaluator.evaluate("clamp(speed, 0.0, 100.0)") == 100.0

def test_ast_evaluator_division_by_zero_safety():
    variables = {"x": 10.0, "zero": 0.0}
    evaluator = SafeFormulaEvaluator(variables)
    
    assert evaluator.evaluate("x / zero") == 0.0

def test_ast_evaluator_disallowed_expressions():
    variables = {"x": 5.0}
    evaluator = SafeFormulaEvaluator(variables)
    
    with pytest.raises(ValueError, match="Disallowed or unknown function"):
        evaluator.evaluate("import_os_system()")

    with pytest.raises(ValueError, match="Undeclared metric variable"):
        evaluator.evaluate("x + undeclared_var")


# ==============================================================================
# BASELINE RESOLUTION TESTS
# ==============================================================================

def test_baseline_resolution_hierarchy(mock_config: MockConfig):
    generator = NominalGenerator(mock_config)
    baselines = generator._entity_baselines

    # Check global fallback
    assert baselines["ENTITY_DEFAULT"]["fuel_level_pct"] == 100.0
    assert baselines["ENTITY_DEFAULT"]["transit_velocity_mph"] == 60.0

    # Check entity-specific override
    assert baselines["ENTITY_OVERRIDE"]["fuel_level_pct"] == 80.0
    assert baselines["ENTITY_OVERRIDE"]["transit_velocity_mph"] == 50.0


# ==============================================================================
# NOMINAL GENERATOR STEP EVALUATION TESTS
# ==============================================================================

def test_evaluate_step_zero_queue_dwell_invariant(mock_config: MockConfig):
    generator = NominalGenerator(mock_config)
    ctx = EntityContext(entity_id="ENTITY_OVERRIDE", entity_type="truck", current_node="DEPOT_A")
    now = datetime(2026, 9, 1, 0, 0, 0)
    dt = timedelta(minutes=1)

    result = generator.evaluate_step(ctx, now, dt)

    # Invariant: queue dwell time is strictly forced to 0.0
    assert result.metrics["queue_dwell_time_min"] == 0.0

def test_evaluate_step_kinematics_advancement(mock_config: MockConfig):
    generator = NominalGenerator(mock_config)
    ctx = EntityContext(
        entity_id="ENTITY_DEFAULT",
        entity_type="truck",
        current_node="DEPOT_A",
        active_route="DEPOT_A->HUB_B",
        route_distance_covered=0.0
    )
    now = datetime(2026, 9, 1, 0, 0, 0)
    dt = timedelta(minutes=15)  # 60 mph for 15 mins = 15 miles

    result = generator.evaluate_step(ctx, now, dt)

    # Route distance = 30 miles. 15 miles covered means entity remains on route
    assert ctx.route_distance_covered == 15.0
    assert result.current_node == "DEPOT_A"

    # Advance another 15 mins -> completes route (30 miles total)
    result_snap = generator.evaluate_step(ctx, now + dt, dt)

    assert ctx.route_distance_covered == 0.0
    assert ctx.active_route is None
    assert result_snap.current_node == "HUB_B"

def test_evaluate_step_dag_task_progress(mock_config: MockConfig):
    generator = NominalGenerator(mock_config)
    ctx = EntityContext(
        entity_id="ENTITY_DEFAULT",
        entity_type="truck",
        current_node="DEPOT_A",
        active_task_id="TASK_INSPECT",
        task_elapsed_min=0.0
    )
    now = datetime(2026, 9, 1, 0, 0, 0)
    dt = timedelta(minutes=10)

    generator.evaluate_step(ctx, now, dt)
    assert ctx.task_elapsed_min == 10.0
    assert ctx.active_task_id == "TASK_INSPECT"

    # Task nominal duration is 15 mins. Advancing another 10 mins completes task
    generator.evaluate_step(ctx, now + dt, dt)
    assert ctx.task_elapsed_min == 0.0
    assert ctx.active_task_id is None

def test_nominal_state_vector_immutability(mock_config: MockConfig):
    generator = NominalGenerator(mock_config)
    ctx = EntityContext(entity_id="ENTITY_DEFAULT", entity_type="truck", current_node="DEPOT_A")
    now = datetime(2026, 9, 1, 0, 0, 0)
    dt = timedelta(minutes=1)

    result = generator.evaluate_step(ctx, now, dt)

    with pytest.raises(FrozenInstanceError):
        result.current_node = "NEW_NODE"