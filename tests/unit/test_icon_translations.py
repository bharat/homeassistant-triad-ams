"""Unit tests for icon translations (Gold requirement)."""

import json
from pathlib import Path


class TestIconTranslations:
    """Test icon translations (Gold requirement)."""

    def test_icons_json_has_translation_structure(self) -> None:
        """Test icons.json has translation structure."""
        # This test will fail until icons.json is updated
        icons_path = (
            Path(__file__).parent.parent.parent
            / "custom_components"
            / "triad_ams"
            / "icons.json"
        )
        with icons_path.open() as f:
            icons = json.load(f)

        # Should have services structure
        assert "services" in icons
        assert "turn_on_with_source" in icons["services"]
        # Service should have service field
        assert "service" in icons["services"]["turn_on_with_source"]

    def test_icon_translations_exist_in_en_json(self) -> None:
        """Test icon translations exist in translations/en.json."""
        # This test will fail until translations are added
        en_path = (
            Path(__file__).parent.parent.parent
            / "custom_components"
            / "triad_ams"
            / "translations"
            / "en.json"
        )
        with en_path.open() as f:
            translations = json.load(f)

        # Should have services section with icon translations
        assert "services" in translations
        assert "turn_on_with_source" in translations["services"]
