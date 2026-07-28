import os
from pathlib import Path
import yaml
import json

def load_yaml_config(config_path: str) -> dict:
    try:
        if not os.path.exists(config_path):
            base_directory = Path(__file__).parent
            config_path = base_directory / config_path
        if not os.path.exists(config_path):
            raise Exception(f"File not found: {config_path}")
        with open(config_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        print(f"File not found: {config_path}")
        raise

def load_json_config(config_path: str) -> dict:
    try:
        if not os.path.exists(config_path):
            base_directory = Path(__file__).parent
            config_path = base_directory / config_path
        if not os.path.exists(config_path):
            raise Exception(f"File not found: {config_path}")
        with open(config_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"File not found: {config_path}")
        raise


# Load agents and tasks configurations
_config_dir = Path(__file__).parent
GLOBAL_AGENTS_CONFIG = load_yaml_config(_config_dir / "agents.yaml")
GLOBAL_TASKS_CONFIG = load_yaml_config(_config_dir / "tasks.yaml")
GLOBAL_TOOLS_CONFIG = load_json_config(_config_dir / "tools.json")

