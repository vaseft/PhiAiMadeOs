"""Disabled capability metadata must never authorize actual noise contents."""
import unittest

from phiaimadeos.inference import _assert_generation_no_noise
from phiaimadeos._model_data import assert_no_noise
from phiaimadeos.models import ModelError


class GenerationNoiseBoundary(unittest.TestCase):
    def test_disabled_ui_request(self):
        _assert_generation_no_noise({"chart_mode": "regular", "noise_area": {"generation_enabled": False}})

    def test_legacy_request_without_declaration(self):
        _assert_generation_no_noise({"chart_mode": "regular"})

    def test_enabled_or_embedded_noise_rejected(self):
        for declaration in ({"generation_enabled": True}, {"generation_enabled": False, "events": [1]},
                            {"generation_enabled": 0}, None, []):
            with self.subTest(declaration=declaration), self.assertRaises(ModelError):
                _assert_generation_no_noise({"noise_area": declaration})

    def test_other_noise_fields_still_rejected(self):
        with self.assertRaises(ModelError):
            _assert_generation_no_noise({"noise_area": {"generation_enabled": False}, "nested": {"noise_events": [1]}})

    def test_raw_training_guard_is_not_relaxed(self):
        with self.assertRaises(ModelError):
            assert_no_noise({"noise_area": {"generation_enabled": False}})
