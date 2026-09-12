import logging
from datetime import datetime, timedelta

from src.config import SimulationConfig
from src.config.invariants import parse_duration_string
from src.simulation.nominal_gen import EntityContext, NominalGenerator, NominalStateVector

logger = logging.getLogger(__name__)


def build_entity_registry(config: SimulationConfig) -> dict[str, EntityContext]:
    """Parses initial entity definitions from config and builds active state context objects."""
    registry: dict[str, EntityContext] = {}
    entities = getattr(config, "entities", [])

    # Extract declared routes and DAG tasks if modules are enabled
    routes = getattr(getattr(config, "network_topology", None), "routes", {}) or {}
    tasks = getattr(getattr(config, "workflow_dag", None), "tasks", []) or []

    for entity in entities:
        entity_id = entity.id if hasattr(entity, "id") else entity["id"]
        entity_type = getattr(entity, "entity_type", "generic_asset")
        initial_loc = getattr(entity, "initial_location", "DEPOT")
        
        # Read initial metrics map
        initial_metrics = getattr(entity, "initial_metrics", None)
        if initial_metrics and hasattr(initial_metrics, "model_dump"):
            initial_metrics = initial_metrics.model_dump()
        elif not initial_metrics:
            initial_metrics = {}

        # Resolve initial active route if network topology is enabled
        active_route = None
        if config.pipeline_toggles.use_network_topology:
            prefix = f"{initial_loc}->"
            matching_routes = [r for r in routes if r.startswith(prefix)]
            if len(matching_routes) > 1:
                logger.warning(
                    f"Multiple candidate routes from '{initial_loc}' for entity '{entity_id}'. "
                    f"Selecting '{matching_routes[0]}'." 
                )
            active_route = matching_routes[0] if matching_routes else None

        # Resolve initial active task if DAG is enabled (find task with no predecessors)
        active_task_id = None
        if config.pipeline_toggles.use_workflow_dag:
            for task in tasks:
                preds = getattr(task, "predecessors", [])
                if not preds:
                    active_task_id = getattr(task, "task_id", None)
                    break

        registry[entity_id] = EntityContext(
            entity_id=entity_id,
            entity_type=entity_type,
            current_node=initial_loc,
            active_route=active_route,
            route_distance_covered=0.0,
            active_task_id=active_task_id,
            task_elapsed_min=0.0,
            is_blocked=False,
            current_metrics=dict(initial_metrics)
        )

    return registry


def run_simulation(config: SimulationConfig) -> None:
    # 1. Initialize time parameters from ISO-8601 config strings
    start_time_str = config.simulation.start_time.replace("Z", "+00:00")
    current_time: datetime = datetime.fromisoformat(start_time_str)
    duration: timedelta = parse_duration_string(config.simulation.duration)
    step_dt: timedelta = parse_duration_string(config.simulation.data_resolution)
    end_time: datetime = current_time + duration

    logger.info(
        f"Starting orchestration loop | Start: {current_time.isoformat()} | "
        f"End: {end_time.isoformat()} | Resolution: {step_dt}"
    )

    # 2. Instantiate engines and entity registry
    entity_registry = build_entity_registry(config)
    nominal_gen = NominalGenerator(config)

    logger.info(f"Initialized registry with {len(entity_registry)} active entities.")

    step_count = 0

    # 3. Time Step Event Loop (t -> t + dt)
    while current_time < end_time:
        step_count += 1

        for entity_id, entity_context in entity_registry.items():
            prev_node = entity_context.current_node
            prev_route = entity_context.active_route

            # --- STEP 1: NOMINAL GENERATOR ---
            payload: NominalStateVector = nominal_gen.evaluate_step(
                entity_context=entity_context,
                current_time=current_time,
                dt=step_dt
            )

            # --- STEP 2: STATE ENGINE (IF TOGGLED) ---
            if config.pipeline_toggles.use_state_engine:
                # payload = state_engine.evaluate_step(payload, entity_context, current_time)
                pass

            # --- STEP 3: REALISM FILTER (IF TOGGLED) ---
            if config.pipeline_toggles.use_realism_filter:
                # payload = realism_filter.evaluate_step(payload, entity_context)
                pass

            # --- STEP 4: MALFORMATIONS FILTER (IF TOGGLED) ---
            if config.pipeline_toggles.use_malformations_filter:
                # payload = malformations_filter.evaluate_step(payload, entity_context)
                pass

            # Log validation telemetry
            logger.debug(
                f"[Step {step_count} | {payload.timestamp}] Entity: {entity_id} | "
                f"Node: {payload.current_node} | Primitives: {payload.metrics} | "
                f"Derivatives: {payload.derivative_metrics}"
            )

            if prev_route and not entity_context.active_route:
                logger.info(
                    f"[ROUTE COMPLETED] Entity '{entity_id}' finished route '{prev_route}'. "
                    f"Arrived at '{entity_context.current_node}'"
                )

            # Update entity context's current metric state to reflect latest evaluated primitives
            entity_context.current_metrics = payload.metrics.copy()

        # Advance global clock
        current_time += step_dt

    logger.info(f"Simulation completed successfully. Processed {step_count} total steps.")