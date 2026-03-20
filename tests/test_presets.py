"""Tests for preset generators — Darktable .dtstyle and Lightroom .xmp."""

import xml.etree.ElementTree as ET
from pathlib import Path

from negclone.models import StockFingerprint
from negclone.presets.darktable import generate_dtstyle
from negclone.presets.lightroom import generate_xmp


class TestDarktablePreset:
    """Tests for Darktable .dtstyle generation."""

    def test_generates_valid_xml(
        self, sample_fingerprint: StockFingerprint, tmp_output: Path
    ) -> None:
        path = generate_dtstyle(sample_fingerprint, tmp_output)

        assert path.exists()
        assert path.suffix == ".dtstyle"

        # Should parse as valid XML
        tree = ET.parse(path)
        root = tree.getroot()
        assert root.tag == "darktable_style"

    def test_contains_info_section(
        self, sample_fingerprint: StockFingerprint, tmp_output: Path
    ) -> None:
        path = generate_dtstyle(sample_fingerprint, tmp_output)
        tree = ET.parse(path)
        root = tree.getroot()

        info = root.find("info")
        assert info is not None

        name = info.find("name")
        assert name is not None
        assert "Portra 400" in (name.text or "")
        assert "Desert Paul" in (name.text or "")

        author = info.find("author")
        assert author is not None
        assert author.text == "Desert Paul"

    def test_contains_expected_modules(
        self, sample_fingerprint: StockFingerprint, tmp_output: Path
    ) -> None:
        path = generate_dtstyle(sample_fingerprint, tmp_output)
        tree = ET.parse(path)
        root = tree.getroot()

        style = root.find("style")
        assert style is not None

        plugins = style.findall("plugin")
        assert len(plugins) >= 3

        module_names = []
        for plugin in plugins:
            module = plugin.find("module")
            assert module is not None
            module_names.append(module.text)

        assert "grain" in module_names
        assert "filmicrgb" in module_names
        assert "colorbalancergb" in module_names

    def test_plugins_have_params(
        self, sample_fingerprint: StockFingerprint, tmp_output: Path
    ) -> None:
        path = generate_dtstyle(sample_fingerprint, tmp_output)
        tree = ET.parse(path)

        for plugin in tree.getroot().findall(".//plugin"):
            params = plugin.find("params")
            assert params is not None
            assert params.text  # Should have base64 content

            enabled = plugin.find("enabled")
            assert enabled is not None
            assert enabled.text == "1"

    def test_xml_encoding(self, sample_fingerprint: StockFingerprint, tmp_output: Path) -> None:
        path = generate_dtstyle(sample_fingerprint, tmp_output)

        with open(path, "rb") as f:
            first_line = f.readline()
        assert b"UTF-8" in first_line


class TestLightroomPreset:
    """Tests for Lightroom .xmp generation."""

    def test_generates_valid_xml(
        self, sample_fingerprint: StockFingerprint, tmp_output: Path
    ) -> None:
        path = generate_xmp(sample_fingerprint, tmp_output)

        assert path.exists()
        assert path.suffix == ".xmp"

        # Should parse as valid XML
        tree = ET.parse(path)
        root = tree.getroot()
        assert "xmpmeta" in root.tag

    def test_has_required_namespaces(
        self, sample_fingerprint: StockFingerprint, tmp_output: Path
    ) -> None:
        path = generate_xmp(sample_fingerprint, tmp_output)

        with open(path, encoding="utf-8") as f:
            content = f.read()

        # Check for required namespace URIs
        assert "adobe:ns:meta/" in content
        assert "http://www.w3.org/1999/02/22-rdf-syntax-ns#" in content
        assert "http://ns.adobe.com/camera-raw-settings/1.0/" in content

    def test_has_grain_params(self, sample_fingerprint: StockFingerprint, tmp_output: Path) -> None:
        path = generate_xmp(sample_fingerprint, tmp_output)

        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert "GrainAmount" in content
        assert "GrainSize" in content
        assert "GrainFrequency" in content

    def test_has_tone_curve(self, sample_fingerprint: StockFingerprint, tmp_output: Path) -> None:
        path = generate_xmp(sample_fingerprint, tmp_output)
        content = path.read_text()
        assert "ToneCurvePV2012" in content

    def test_has_color_grading(
        self, sample_fingerprint: StockFingerprint, tmp_output: Path
    ) -> None:
        path = generate_xmp(sample_fingerprint, tmp_output)

        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert "ColorGradeShadowHue" in content
        assert "ColorGradeMidtoneHue" in content
        assert "ColorGradeHighlightHue" in content
        assert "ShadowTint" in content

    def test_has_process_version(
        self, sample_fingerprint: StockFingerprint, tmp_output: Path
    ) -> None:
        path = generate_xmp(sample_fingerprint, tmp_output)

        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert "ProcessVersion" in content
        assert "11.0" in content

    def test_xmp_encoding(self, sample_fingerprint: StockFingerprint, tmp_output: Path) -> None:
        path = generate_xmp(sample_fingerprint, tmp_output)

        with open(path, "rb") as f:
            first_line = f.readline()
        assert b"UTF-8" in first_line
