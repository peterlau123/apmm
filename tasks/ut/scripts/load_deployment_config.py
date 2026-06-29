"""load_deployment_config.py - Load workflow config from deployment or fixtures."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def load_deployment_config(env: str, level: int | None = None) -> Path:
    """Load workflow config from deployment or fixtures.

    Args:
        env: "production" or "test"
        level: 1-4 for test environment (l1~l4)

    Returns:
        Path to workflow.yaml template

    Raises:
        ValueError: Invalid env or level
        FileNotFoundError: Template not found
    """
    if env == "production":
        template_path = PROJECT_ROOT / "tasks/ut/deployment/production/config/workflow.yaml"
    elif env == "test":
        if level not in [1, 2, 3, 4]:
            raise ValueError(f"Test environment requires level 1-4, got: {level}")
        template_path = PROJECT_ROOT / f"tests/ut/integration/fixtures/workflow.l{level}.yaml"
    else:
        raise ValueError(f"Invalid env: {env}. Must be 'production' or 'test'")

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    return template_path