"""Tests for embedding model registry."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

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
    EmbeddingRegistry._instance_cache = {}
    yield
    EmbeddingRegistry._instance = None
    EmbeddingRegistry._model = {}
    EmbeddingRegistry._instance_cache = {}


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

    def test_is_loaded_false_before_create(self):
        registry = EmbeddingRegistry()
        registry.register("dummy", DummyEmbedding)
        assert not registry.is_loaded("dummy")

    def test_preload_returns_cached_instance(self):
        registry = EmbeddingRegistry()
        registry.register("dummy", DummyEmbedding)

        preloaded = registry.preload("dummy")
        assert isinstance(preloaded, DummyEmbedding)
        assert registry.is_loaded("dummy")
        assert registry.create("dummy") is preloaded

    def test_preload_default_model(self):
        registry = EmbeddingRegistry()
        registry.register("Qwen/Qwen3-Embedding-0.6B", DummyEmbedding)

        preloaded = registry.preload()
        assert registry.is_loaded()
        assert registry.create() is preloaded

    def test_concurrent_create_loads_model_once(self):
        """并发 create（模拟后台预加载与首次请求）只应触发一次实际加载。"""
        load_count = 0

        class SlowEmbedding(EmbeddingModel):
            def __init__(self) -> None:
                nonlocal load_count
                time.sleep(0.05)  # 模拟耗时的模型加载
                load_count += 1

            def embed(self, text: str) -> list[float]:
                return [0.0]

            def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [[0.0] for _ in texts]

        registry = EmbeddingRegistry()
        registry.register("slow", SlowEmbedding)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(registry.create, "slow") for _ in range(4)]
            results = [f.result() for f in futures]

        assert load_count == 1
        assert all(r is results[0] for r in results)
