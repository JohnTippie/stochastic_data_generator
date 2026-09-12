from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from src.config.formulas import SafeFormulaEvaluator, validate_derivative_metric_formulas

# ====================================
# DATA STRUCTURES
# ====================================

@dataclass(frozen=True)
class NominalStateVector:
    """
    Immutable uncorrupted target state emitted by Nominal Generator for tick t
    """
    timestamp: str
    entity_id: str
    current_node: str
    metrics: Dict[str,float]
    derivative_metrics: Dict[str, float]

@dataclass
class EntityContext:
    """
    Mutable entity context tracked by the Simulation Orchestrator across ticks
    """
    entity_id: str
    entity_type: str
    current_node: str
    active_route: Optional[str] = None
    route_distance_covered: Optional[float] = 0.0
    active_task_id: Optional[str] = None
    task_elapsed_min: float = 0.0
    is_blocked: bool = False
    current_metrics: Dict[str, float] = field(default_factory=dict)

# ====================================
# NOMINAL GENERATOR ENGINE
# ====================================

class NominalGenerator:
    """
    Pure baseline engine calculating target metric vectors and ideal progress.
    """

    def __init__(self, config: Any):
        self.config = config
        self._entity_baselines: Dict[str, Dict[str,float]] = self._resolve_baselines()
        self._sorted_derivative_metrics = [
            m for m in validate_derivative_metric_formulas(self.config.metrics)
        ]

    def evaluate_step(
        self, 
        entity_context: EntityContext, 
        current_time: datetime, 
        dt: timedelta
    ) -> NominalStateVector:
        """Calculates target uncorrupted state vector for step dt."""
        
        # 1. Fetch uncorrupted baseline primitive metrics
        entity_id = entity_context.entity_id
        primitive_metrics = self._entity_baselines[entity_id].copy()

        # Enforce zero friction / zero queue defaults
        if "queue_dwell_time_min" in primitive_metrics:
            primitive_metrics["queue_dwell_time_min"] = 0.0

        # 2. Ideal Topology Kinematics
        current_node = entity_context.current_node
        if self.config.pipeline_toggles.use_network_topology:
            current_node = self._evaluate_ideal_kinematics(entity_context, dt, primitive_metrics)

        # 3. Ideal Workflow DAG Progress
        if self.config.pipeline_toggles.use_workflow_dag:
            self._evaluate_ideal_dag_progress(entity_context, dt)

        # 4. AST Derivative Metric Evaluation
        derivative_metrics = self._evaluate_derivative_metrics(primitive_metrics)

        # 5. Build and return immutable vector payload
        return NominalStateVector(
            timestamp=current_time.isoformat(),
            entity_id=entity_id,
            current_node=current_node,
            metrics=primitive_metrics,
            derivative_metrics=derivative_metrics
        )

    def _resolve_baselines(self) -> Dict[str, Dict[str, float]]:
        """Pre-evaluates baseline metric overrides per entity at startup."""
        resolved: Dict[str, Dict[str, float]] = {}
        global_baseline = self.config.nominal_generator.baseline_metrics

        for entity in self.config.entities:
            initial = entity.initial_metrics if entity.initial_metrics is not None else global_baseline
            resolved[entity.id] = dict(initial)
        return resolved

    def _evaluate_ideal_kinematics(
        self, 
        entity_context: EntityContext, 
        dt: timedelta, 
        primitive_metrics: Dict[str, float]
    ) -> str:
        """Evaluates uncorrupted spatial movement along network topology routes."""
        if not entity_context.active_route or not self.config.network_topology or not self.config.network_topology.routes:
            return entity_context.current_node

        route_info = self.config.network_topology.routes.get(entity_context.active_route)
        if not route_info:
            return entity_context.current_node

        # Extract max speed constraint
        max_route_speed = float(route_info.max_route_speed)
        distance_miles = float(route_info.distance_miles)

        # Enforce nominal speed metric
        if "transit_velocity_mph" in primitive_metrics:
            primitive_metrics["transit_velocity_mph"] = max_route_speed

        # Advance distance using ideal velocity: dist = v * dt
        dt_hours = dt.total_seconds() / 3600.0
        ideal_step_distance = max_route_speed * dt_hours
        entity_context.route_distance_covered += ideal_step_distance

        # Check route completion
        if entity_context.route_distance_covered >= distance_miles:
            # Snap to destination node
            _, dest_node = entity_context.active_route.split("->")
            entity_context.current_node = dest_node
            entity_context.active_route = None
            entity_context.route_distance_covered = 0.0

        return entity_context.current_node

    def _evaluate_ideal_dag_progress(self, entity_context: EntityContext, dt: timedelta) -> None:
        """Advances active DAG task duration assuming zero resource constraints."""
        if not entity_context.active_task_id:
            return

        dt_minutes = dt.total_seconds() / 60.0
        entity_context.task_elapsed_min += dt_minutes

        # Look up nominal duration for task
        task_spec = next(
            (t for t in self.config.workflow_dag.tasks if t.task_id == entity_context.active_task_id),
            None
        )

        if task_spec:
            nominal_duration = float(task_spec.nominal_duration_min)
            if entity_context.task_elapsed_min >= nominal_duration:
                entity_context.active_task_id = None
                entity_context.task_elapsed_min = 0.0

    def _evaluate_derivative_metrics(self, primitive_metrics: Dict[str, float]) -> Dict[str, float]:
        """Calculates derived metrics using AST expression engine."""
        derived_results: Dict[str, float] = {}
        eval_scope = primitive_metrics.copy()
        evaluator = SafeFormulaEvaluator(eval_scope)

        for metric_def in self._sorted_derivative_metrics:
            if metric_def.formula:
                val = evaluator.evaluate(metric_def.formula)
                derived_results[metric_def.name] = val
                eval_scope[metric_def.name] = val

        return derived_results