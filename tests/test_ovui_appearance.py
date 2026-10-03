"""Persistent preferences and complete, repeatable theme application."""

import json
from pathlib import Path
import pytest

from omnilab.frontends.ovui.appearance import Appearance, THEMES, settings_path


def test_preferences_round_trip_and_ignore_future_fields(tmp_path):
    path = tmp_path / "preferences/appearance.json"
    settings = Appearance("showcase_teal", "comfortable")
    settings.save(path)
    data = json.loads(path.read_text())
    data["future_option"] = True
    path.write_text(json.dumps(data))
    assert Appearance.load(path) == settings


@pytest.mark.parametrize(
    "contents",
    ["{bad", "[]", "null", '{"theme":"missing"}', '{"density":42}', '{"theme":[]}'],
)
def test_invalid_preferences_recover_to_defaults(tmp_path, contents):
    path = tmp_path / "appearance.json"
    path.write_text(contents)
    assert Appearance.load(path) == Appearance()


def test_preferences_use_per_user_ovui_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert settings_path() == tmp_path / "omnilab/ovui/appearance.json"
    assert Appearance.load() == Appearance()
    Appearance("light").save()
    assert Appearance.load() == Appearance("light")


def test_apply_palette_repeatably_and_keep_density_independent():
    pytest.importorskip("ovui_widgets.app")
    import omni.ui as ui
    from omnilab.frontends.ovui.style import apply_style
    from omnilab.core.fixtures import demo_document

    document = demo_document()
    before = document.stage.GetRootLayer().ExportToString()
    colors = {}
    for theme in [*THEMES, "dark"]:
        apply_style(Appearance(theme, "compact"))
        colors[theme] = ui.ColorStore.find("accent_primary")
        assert ui.FloatStore.find("font_size_medium") == 14
        assert ui.FloatStore.find("spacing_small") == 4
        assert ui.FloatStore.find("radius_small") == 3
        assert ui.ColorStore.find("text_primary") == (
            0xFF111111 if theme == "light" else 0xFFE0E0E0
        )
        styles = ui.style.default
        assert styles["Label"]["font_size"] == 14
        assert Path(styles["Label"]["font"]).is_file()
        for key in (
            "Button",
            "Property.ValueField",
            "Stage.Name",
            "Layers.TreeView",
            "Content.TreeView",
            "Material.Connection",
        ):
            assert key in styles
    assert len({colors[theme] for theme in THEMES if theme != "light"}) == 4
    for theme in ("light", "showcase_orange", "dark"):
        apply_style(Appearance(theme, "comfortable"))
        assert ui.FloatStore.find("font_size_medium") == 16
        assert ui.style.default["Label"]["font_size"] == 16
        assert ui.FloatStore.find("spacing_small") == 6
        assert ui.ColorStore.find("accent_primary") == colors[theme]
    assert document.stage.GetRootLayer().ExportToString() == before
    assert not document.edits.undo
    apply_style(Appearance())
