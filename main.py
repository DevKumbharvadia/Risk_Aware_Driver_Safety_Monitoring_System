
"""Command-line entry point for Fleet Guardian (Cloudflare Quick Tunnel only)."""

import argparse
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import secrets

from fleet.manager.phone_manager import run_manager


PROJECT_DIR = Path(__file__).resolve().parent


def load_config(path):
    """Load configuration or create secure access tokens."""

    path = Path(path)

    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                f"Could not read configuration file {path}: {error}"
            ) from error

        if not isinstance(config, dict):
            raise ValueError("Configuration must contain a JSON object.")

        for name in ("owner_token", "device_token"):
            value = config.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Configuration field '{name}' must be a non-empty string."
                )

        return config

    config = {
        "owner_token": secrets.token_urlsafe(24),
        "device_token": secrets.token_urlsafe(24),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")

    try:
        temporary_path.write_text(
            json.dumps(config, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass

    return config


def configure_logging(data_dir):
    """Configure rotating file logging."""

    handler = RotatingFileHandler(
        Path(data_dir) / "fleet.log",
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[handler],
        force=True,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Fleet Guardian — Cloudflare Quick Tunnel fleet manager"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_DIR / "data",
        help="Data directory for the database, logs and configuration",
    )

    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)

    configure_logging(args.data_dir)

    try:
        config = load_config(args.data_dir / "config.json")
    except ValueError as error:
        logging.exception("Configuration loading failed.")
        parser.error(str(error))

    logging.info("Starting Fleet Guardian.")

    try:
        run_manager(args, config)
    except KeyboardInterrupt:
        logging.info("Fleet Guardian stopped by user.")
    except Exception:
        logging.exception("Fleet Guardian stopped due to an error.")
        raise


if __name__ == "__main__":
    main()
