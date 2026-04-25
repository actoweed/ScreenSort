"""CLIP-based zero-shot image classifier."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NamedTuple

import open_clip
import torch
from PIL import Image

logger = logging.getLogger(__name__)


class ClassificationResult(NamedTuple):
    category: str
    confidence: float
    all_scores: dict[str, float]


class Classifier:
    def __init__(
        self,
        categories: dict[str, dict],
        model_name: str = "ViT-B-32",
        pretrained: str = "openai",
        confidence_threshold: float = 0.20,
    ) -> None:
        self.categories = categories
        self.confidence_threshold = confidence_threshold
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._text_features: dict[str, torch.Tensor] = {}
        self._model_name = model_name
        self._pretrained = pretrained
        self._device = "cuda" if torch.cuda.is_available() else "cpu"

    def _load_model(self) -> None:
        if self._model is not None:
            return

        logger.info(
            "Loading CLIP model %s/%s on %s (first run downloads ~350 MB)…",
            self._model_name,
            self._pretrained,
            self._device,
        )
        model, _, preprocess = open_clip.create_model_and_transforms(
            self._model_name,
            pretrained=self._pretrained,
        )
        model = model.to(self._device).eval()
        tokenizer = open_clip.get_tokenizer(self._model_name)

        self._model = model
        self._preprocess = preprocess
        self._tokenizer = tokenizer
        self._encode_text_prompts()

    def _encode_text_prompts(self) -> None:
        """Pre-encode all category prompts into text feature vectors."""
        with torch.no_grad():
            for category, info in self.categories.items():
                prompts = info.get("prompts", [info.get("description", category)])
                tokens = self._tokenizer(prompts).to(self._device)
                features = self._model.encode_text(tokens)
                features = features / features.norm(dim=-1, keepdim=True)
                # Average over all prompts for this category
                self._text_features[category] = features.mean(dim=0)

    def classify(self, image_path: Path) -> ClassificationResult | None:
        """Classify an image and return its category with confidence score."""
        self._load_model()

        try:
            image = Image.open(image_path).convert("RGB")
        except Exception as exc:
            logger.warning("Cannot open %s: %s", image_path, exc)
            return None

        try:
            image_tensor = self._preprocess(image).unsqueeze(0).to(self._device)
        except Exception as exc:
            logger.warning("Cannot preprocess %s: %s", image_path, exc)
            return None

        with torch.no_grad():
            image_features = self._model.encode_image(image_tensor)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)

        # Exclude 'other' from softmax — it would absorb probability mass
        # from real categories and push everything toward low confidence.
        real_categories = [c for c in self._text_features if c != "other"]
        text_matrix = torch.stack(
            [self._text_features[c] for c in real_categories]
        )

        similarities = (image_features @ text_matrix.T).squeeze(0)
        probs = similarities.softmax(dim=-1).cpu().tolist()

        scores: dict[str, float] = {}
        for cat, prob in zip(real_categories, probs):
            scores[cat] = round(float(prob), 4)
        if "other" in self._text_features:
            scores["other"] = 0.0

        best_category = max(real_categories, key=lambda c: scores[c])
        best_score = scores[best_category]

        if best_score < self.confidence_threshold:
            best_category = "other"

        return ClassificationResult(
            category=best_category,
            confidence=best_score,
            all_scores=scores,
        )
