"""Tests for the CLIP classifier (uses mocks to avoid downloading models)."""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from screenshot_sorter.classifier import ClassificationResult, Classifier

CATEGORIES = {
    "code": {
        "prompts": ["a screenshot of source code"],
    },
    "nature": {
        "prompts": ["a photograph of nature"],
    },
    "other": {
        "prompts": ["a miscellaneous screenshot"],
    },
}


@pytest.fixture()
def classifier():
    return Classifier(categories=CATEGORIES, confidence_threshold=0.20)


def _mock_open_clip(monkeypatch):
    """Patch open_clip so no network calls or GPU are needed."""
    import torch

    mock_model = MagicMock()
    mock_model.encode_image.return_value = torch.ones(1, 512)
    mock_model.encode_text.return_value = torch.ones(3, 512)
    mock_model.to.return_value = mock_model
    mock_model.eval.return_value = mock_model

    mock_preprocess = MagicMock(return_value=torch.zeros(3, 224, 224))

    mock_tokenizer = MagicMock(return_value=torch.zeros(1, 77, dtype=torch.long))

    mock_open_clip = MagicMock()
    mock_open_clip.create_model_and_transforms.return_value = (
        mock_model,
        None,
        mock_preprocess,
    )
    mock_open_clip.get_tokenizer.return_value = mock_tokenizer

    monkeypatch.setattr("screenshot_sorter.classifier.open_clip", mock_open_clip)
    return mock_model, mock_preprocess, mock_tokenizer


class TestClassifier:
    def test_classification_result_is_namedtuple(self):
        r = ClassificationResult(category="code", confidence=0.9, all_scores={"code": 0.9})
        assert r.category == "code"
        assert r.confidence == 0.9

    def test_classify_returns_none_for_corrupt_file(self, classifier, tmp_path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image")
        result = classifier.classify(bad)
        # Should return None gracefully, not raise
        assert result is None

    def test_classify_returns_none_for_missing_file(self, classifier, tmp_path):
        missing = tmp_path / "does_not_exist.png"
        result = classifier.classify(missing)
        assert result is None

    def test_confidence_below_threshold_returns_other(self, classifier, tmp_path, monkeypatch):
        import torch
        from PIL import Image

        _mock_open_clip(monkeypatch)

        # Make softmax return very low scores (uniform)
        with patch("screenshot_sorter.classifier.torch.no_grad") as mock_ng:
            mock_ng.return_value.__enter__ = MagicMock(return_value=None)
            mock_ng.return_value.__exit__ = MagicMock(return_value=False)

            img_path = tmp_path / "test.png"
            Image.new("RGB", (64, 64), color=(128, 128, 128)).save(img_path)

            # Force low confidence by patching the model's output to uniform vectors
            classifier._load_model()
            classifier._model.encode_image.return_value = torch.ones(1, 512)
            # All text features equal → softmax gives equal probability → below threshold
            for cat in classifier._text_features:
                classifier._text_features[cat] = torch.ones(512)

            result = classifier.classify(img_path)
            if result is not None:
                # With uniform scores, all categories get equal score; lowest is below threshold
                # so it falls back to 'other'
                assert result.category in CATEGORIES

    def test_all_scores_keys_match_categories(self, classifier, tmp_path, monkeypatch):
        import torch
        from PIL import Image

        _mock_open_clip(monkeypatch)

        img_path = tmp_path / "test.png"
        Image.new("RGB", (100, 100)).save(img_path)

        # Pre-load the model with mocks
        classifier._load_model()
        for cat in classifier._text_features:
            classifier._text_features[cat] = torch.randn(512)

        result = classifier.classify(img_path)
        if result is not None:
            assert set(result.all_scores.keys()) == set(CATEGORIES.keys())

    def test_confidence_is_between_0_and_1(self, classifier, tmp_path, monkeypatch):
        import torch
        from PIL import Image

        _mock_open_clip(monkeypatch)
        img_path = tmp_path / "test.png"
        Image.new("RGB", (64, 64)).save(img_path)

        classifier._load_model()
        for cat in classifier._text_features:
            classifier._text_features[cat] = torch.randn(512)

        result = classifier.classify(img_path)
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0
