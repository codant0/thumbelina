"""Tests for embedding model registry."""

from __future__ import annotations

import pytest

from thumbelina.rag.embedding.base import EmbeddingModel
from thumbelina.rag.embedding.registry import EmbeddingRegistry


class DummyEmbedding(EmbeddingModel):
    """用于测试的简易 EmbeddingModel。"""

    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


@pytest.fixture(autouse=True)
def _reset_singleton():
    """每个测试前重置单例状态。"""
    EmbeddingRegistry._instance = None
    EmbeddingRegistry._model = {}
    yield
    EmbeddingRegistry._instance = None
    EmbeddingRegistry._model = {}


class TestEmbeddingRegistry:
    """Tests for EmbeddingRegistry."""

    def test_singleton_pattern(self):
        r1 = EmbeddingRegistry()
        r2 = EmbeddingRegistry()
        assert r1 is r2

    def test_register_and_create(self):
        registry = EmbeddingRegistry()
        registry.register("dummy", DummyEmbedding)

        model = registry.create("dummy")
        assert isinstance(model, DummyEmbedding)

    def test_create_unknown_model_raises(self):
        registry = EmbeddingRegistry()
        with pytest.raises(ValueError, match="Unknown embedding model"):
            registry.create("nonexistent_model")

    def test_create_with_default_model(self):
        registry = EmbeddingRegistry()
        registry.register("Qwen/Qwen3-Embedding-0.6B", DummyEmbedding)

        model = registry.create()  # 不传参数，使用默认
        assert isinstance(model, DummyEmbedding)

    def test_register_multiple_models(self):
        class AnotherEmbedding(EmbeddingModel):
            def embed(self, text: str) -> list[float]:
                return [0.5]

            def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [[0.5] for _ in texts]

        registry = EmbeddingRegistry()
        registry.register("model_a", DummyEmbedding)
        registry.register("model_b", AnotherEmbedding)

        assert isinstance(registry.create("model_a"), DummyEmbedding)
        assert isinstance(registry.create("model_b"), AnotherEmbedding)

    def test_register_overwrites_existing(self):
        class OverrideEmbedding(EmbeddingModel):
            def embed(self, text: str) -> list[float]:
                return [0.9]

            def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [[0.9] for _ in texts]

        registry = EmbeddingRegistry()
        registry.register("dummy", DummyEmbedding)
        registry.register("dummy", OverrideEmbedding)

        model = registry.create("dummy")
        assert isinstance(model, OverrideEmbedding)
