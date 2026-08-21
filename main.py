import sys
from pathlib import Path
from custom_utils.formatted_logger import create_logger, update_logger_level
from src.config import ConfigReader, ConfigError, SimulationConfig


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
    except ConfigError as e:
        logger.error(f"Configuration ingestion failed: {e}")
        raise ConfigError(f"Configuration error encountered: {e}") from e
    except Exception as e:
        logger.critical(f"Unexpected error occured during configuration startup: {e}")
        raise ConfigError(f"Unknown error encountered: {e}") from e

    # ====================================
    # Nominal Generator
    # ====================================

    # ====================================
    # State Engine
    # ====================================

    # ====================================
    # Realism Filter
    # ====================================

    # ====================================
    # Malformations Filter
    # ====================================

    # ====================================
    # File Sink
    # ====================================
    

if __name__ == "__main__":
    sys.exit(main())