import sys
from pathlib import Path
from custom_utils.formatted_logger import create_logger, update_logger_level
from src.config import ConfigReader, ConfigError, SimulationConfig
from src.simulation.orchestrator import run_simulation


def main() -> int:

    # Initialize Logger
    try:
        logger = create_logger()
        logger.info("Logger initialized.")
    except Exception as e:
        raise RuntimeError("Logger failed to initialize") from e

    log_level = "DEBUG"
    logger = update_logger_level(log_level, logger)
    logger.info(f"Updated logging level to {log_level}")

    # Resolve Target Config Path
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.yaml")

    # ====================================
    # Config Reader
    # ====================================
    try:
        logger.info(f"Loading configuration from: {config_path}")
        config: SimulationConfig = ConfigReader.load_config(config_path)
        logger.info(f"Configuration validated successfully. "
                    f"Run seed: '{config.meta.seed}', Entities: {len(config.entities)}")

        run_simulation(config)
        logger.info("Simulation completed successfully.")
    except ConfigError as e:
        logger.error(f"Configuration ingestion failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Unexpected runtime error in simulation execution loop: {e}")
        sys.exit(2)

    

if __name__ == "__main__":
    sys.exit(main())