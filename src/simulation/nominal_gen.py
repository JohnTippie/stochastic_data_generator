import ast
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

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
    route_distance_covered: Optional[float] = None
    active_task_id: Optional[str] = None
    task_elapsed_min: float = 0.0
    is_blocked: bool = False
    current_metrics: Dict[str, float] = field(default_factory=dict)

# ====================================
# AST EVALUATOR
# ====================================
class SafeFormulaEvaluator(ast.NodeVisitor):
    """
    Evaluate sanitized AST expressions
    """

    ALLOWED_FUNCTIONS = {
        "abs": abs,
        "min": min,
        "max": max,
        "sqrt": math.sqrt,
        "log": math.log,
        "exp": math.exp,
        "pow": pow,
        "clamp": lambda val, low, high: max(low, min(val, high)),
    }

    def __init__(self, variables: Dict[str, float]):
        self.variables = variables

    def evaluate(self, expression: str) -> float:
        parsed_ast = ast.parse(expression, mode="eval")
        return float(self.visit(parsed_ast.body))

    def visit_Num(self, node: ast.Num) -> float:
        return float(node.n)

    def visit_Constant(self, node: ast.Constant) -> float:
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsupported constant type: {type(node.value)}")

    def visit_Name(self, node: ast.Name) -> float:
        if node.id in self.variables:
            return float(self.variables[node.id])
        raise ValueError(f"Undeclared metric variable in AST evaluation: '{node.id}'")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> float:
        operand = self.vist(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise ValueError(f"Unsupported unary operator: {type(node.op)}")

    def visit_BinOp(self, node: ast.BinOp) -> float:
        left = self.visit(node.left)
        right = self.visit(node.right)

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right if right != 0.0 else 0.0
        if isinstance(node.op, ast.Pow):
            return left ** right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise ValueError(f"Unsupported binary operator: {type(node.op)}")

    def visit_Call(self, node: ast.Call) -> float:
        if not isinstance(node.func, ast.Name) or node.func.id not in self.ALLOWED_FUNCTIONS:
            raise ValueError(f"Disallowed or unknown function call in AST: '{getattr(node.func, 'id', None)}'")

        args = [self.visit(arg) for arg in node.args]
        func = self.ALLOWED_FUNCTIONS[node.func.id]
        return float(func(*args))

    def generic_visit(self, node: ast.AST):
        raise ValueError(f"Disallowed AST expression syntax: {type(node).__name__}")

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
        if getattr(self.config.pipeline_toggles, "use_network_topology", False):
            current_node = self._evaluate_ideal_kinematics(entity_context, dt, primitive_metrics)

        # 3. Ideal Workflow DAG Progress
        if getattr(self.config.pipeline_toggles, "use_workflow_dag", False):
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
        
        # Read global fallback
        global_baseline = getattr(self.config.nominal_generator, "baseline_metrics", {})
        if hasattr(global_baseline, "model_dump"):
            global_baseline = global_baseline.model_dump()

        # Map entities
        entities = getattr(self.config, "entities", [])
        for entity in entities:
            entity_id = entity.id if hasattr(entity, "id") else entity["id"]
            initial_metrics = getattr(entity, "initial_metrics", None) or getattr(entity, "metrics", None)
            
            if initial_metrics:
                if hasattr(initial_metrics, "model_dump"):
                    initial_metrics = initial_metrics.model_dump()
                resolved[entity_id] = dict(initial_metrics)
            else:
                resolved[entity_id] = dict(global_baseline)

        return resolved

    def _evaluate_ideal_kinematics(
        self, 
        entity_context: EntityContext, 
        dt: timedelta, 
        primitive_metrics: Dict[str, float]
    ) -> str:
        """Evaluates uncorrupted spatial movement along network topology routes."""
        if not entity_context.active_route:
            return entity_context.current_node

        routes = getattr(self.config.network_topology, "routes", {})
        route_info = routes.get(entity_context.active_route)
        
        if not route_info:
            return entity_context.current_node

        # Extract max speed constraint
        max_route_speed = float(getattr(route_info, "max_route_speed", 65.0))
        distance_miles = float(getattr(route_info, "distance_miles", 0.0))

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
        tasks = getattr(self.config.workflow_dag, "tasks", [])
        task_spec = next((t for t in tasks if getattr(t, "task_id", None) == entity_context.active_task_id), None)

        if task_spec:
            nominal_duration = float(getattr(task_spec, "nominal_duration_min", 0.0))
            if entity_context.task_elapsed_min >= nominal_duration:
                entity_context.active_task_id = None
                entity_context.task_elapsed_min = 0.0

    def _evaluate_derivative_metrics(self, primitive_metrics: Dict[str, float]) -> Dict[str, float]:
        """Calculates derived metrics using AST expression engine."""
        derived_results: Dict[str, float] = {}
        metrics_decl = getattr(self.config, "metrics", [])

        evaluator = SafeFormulaEvaluator(primitive_metrics)

        for metric_def in metrics_decl:
            is_derivative = getattr(metric_def, "is_derivative", False)
            if is_derivative:
                name = getattr(metric_def, "name")
                formula = getattr(metric_def, "formula", None)
                if formula:
                    derived_results[name] = evaluator.evaluate(formula)

        return derived_results