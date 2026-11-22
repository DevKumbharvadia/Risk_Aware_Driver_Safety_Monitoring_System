"""Command-line entry point. Run `python main.py` for the phone-camera fleet manager."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import secrets

from fleet.manager.phone_manager import run_manager

PROJECT_DIR = Path(__file__).resolve().parent


def load_config(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    config = {"owner_token": secrets.token_urlsafe(24), "device_token": secrets.token_urlsafe(24)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def main():
    parser = argparse.ArgumentParser(description="Fleet Guardian — phone-camera fleet manager")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR / "data", help="Data directory for the database, logs and certificates")
    parser.add_argument("--trip", action="store_true", help="Expose the phone service over a temporary Cloudflare HTTPS tunnel")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    log_file = args.data_dir / "fleet.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
    config = load_config(args.data_dir / "config.json")
    run_manager(args, config)


if __name__ == "__main__":
    main()
