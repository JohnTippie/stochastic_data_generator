from pathlib import Path
from src.config.reader import load_config, ConfigReader
from src.config.schemas import SimulationConfig
from conftest import write_yaml

def test_happy_path_maximal_kitchen_sink_config(valid_config_dict: dict, tmp_path: Path):
    """Happy Path: Tests fully loaded configuration with all engines active."""
    file_path = write_yaml(valid_config_dict, tmp_path)
    config = ConfigReader.load_config(file_path)

    assert isinstance(config, SimulationConfig)
    assert config.pipeline_toggles.use_state_engine is True
    assert config.pipeline_toggles.use_realism_filter is True
    assert config.state_engine is not None
    assert len(config.state_engine.states) > 0
    assert len(config.state_engine.macro_shocks) > 0

def test_happy_path_minimal_nominal_config(tmp_path: Path):
    """Happy Path: Tests bare-bones configuration with optional engines disabled."""
    out_file = tmp_path / "minimal.csv"
    minimal_dict = {
        "meta": {
            "scenario_name": "minimal_scenario",
            "description": "Minimal baseline test",
            "seed": 42,
        },
        "simulation": {
            "start_time": "2026-01-01T00:00:00Z",
            "duration": "1d",
            "data_resolution": "1h",
            "epoch_interval": "1h",
        },
        "pipeline_toggles": {
            "use_state_engine": False,
            "use_network_topology": False,
            "use_resource_contention": False,
            "use_workflow_dag": False,
            "use_realism_filter": False,
            "use_malformations_filter": False,
        },
        "metrics": [
            {
                "name": "primary_metric",
                "is_derivative": False,
                "primitive_type": "float",
            }
        ],
        "nominal_generator": {
            "baseline_metrics": {"primary_metric": 10.0}
        },
        "entities": [
            {
                "id": "bare_entity",
                "entity_type": "unit",
                "initial_location": "DEPOT",
                "initial_state": "NOMINAL",
                "initial_metrics": {"primary_metric": 10.0},
            }
        ],
        "sink": {
            "format": "csv",
            "output_path": str(out_file),
            "metadata_toggles": {
                "include_state": False,
                "include_malformed_flag": False,
                "include_true_baseline": False,
            },
            "fields": [{"name": "val", "source": "metrics.primary_metric"}],
        },
    }

    file_path = write_yaml(minimal_dict, tmp_path)
    config = ConfigReader.load_config(file_path)

    assert isinstance(config, SimulationConfig)
    assert config.pipeline_toggles.use_state_engine is False
    assert config.state_engine is None
    assert config.network_topology is None

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