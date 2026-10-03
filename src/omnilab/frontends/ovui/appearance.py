"""User appearance preferences, independent of USD/project state."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path

from omnilab.core.document import atomic_json

THEMES = {
    "dark": "OvGear Dark",
    "light": "OvGear Light",
    "showcase_orange": "Showcase Orange",
    "showcase_blue": "Showcase Blue",
    "showcase_teal": "Showcase Teal",
}
DENSITIES = {"compact": "Compact", "comfortable": "Comfortable"}


def settings_path():
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "omnilab/ovui/appearance.json"
    )


@dataclass(frozen=True)
class Appearance:
    theme: str = "dark"
    density: str = "compact"

    def __post_init__(self):
        if self.theme not in THEMES or self.density not in DENSITIES:
            raise ValueError("Choose a supported appearance theme and density.")

    @classmethod
    def load(cls, path=None):
        try:
            data = json.loads(Path(path or settings_path()).read_text())
            return cls(
                theme=data.get("theme", "dark"), density=data.get("density", "compact")
            )
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()

    def save(self, path=None):
        path = Path(path or settings_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, dict(version=1, **asdict(self)))
