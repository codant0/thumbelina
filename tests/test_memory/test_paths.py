"""路径穿越与符号链接逃逸测试(设计文档 §8.3、§13 任务 14)。

``_resolve`` 是 memory 包所有读写的唯一路径来源,``category``/``slug``
由 LLM 输出、也可经 API 传入,是半受控输入,必须集中校验以杜绝路径
穿越与符号链接逃逸。``resolve_index`` 固定返回 ``base/index.md``。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from thumbelina.memory.paths import INDEX_FILENAME, _resolve, resolve_index


class TestResolveRejects:
    """非法 category/slug 全部抛 ValueError 且不逃逸 base。"""

    @pytest.mark.parametrize(
        "category,slug",
        [
            ("..", "x"),
            ("../x", "y"),
            ("user", "../x"),
            ("user", ".."),
            ("user\\evil", "x"),
            ("user", "evil\\x"),
            ("user/x", "y"),
            ("user", "a/b"),
            (".hidden", "x"),
            ("user", ".hidden"),
            ("", "x"),
            ("user", ""),
            ("%2e%2e", "x"),
            ("user", "%2e%2e"),
            ("USER", "x"),
            ("User", "x"),
            ("user", "Slug"),
            ("user", " Slug"),
            ("user", "slug!"),
            ("user", "slug.dot"),
        ],
    )
    def test_illegal_raises(self, tmp_path: Path, category: str, slug: str) -> None:
        with pytest.raises(ValueError):
            _resolve(tmp_path, category, slug)

    def test_super_long_slug_rejected(self, tmp_path: Path) -> None:
        # slug 上限 129 字符(首字符 + 后续 128);超出应拒绝。
        long_slug = "a" * 130
        with pytest.raises(ValueError):
            _resolve(tmp_path, "user", long_slug)

    def test_super_long_category_rejected(self, tmp_path: Path) -> None:
        long_cat = "a" * 66
        with pytest.raises(ValueError):
            _resolve(tmp_path, long_cat, "x")


class TestResolveAccepts:
    """合法 slug/category 通过并解析正确路径。"""

    @pytest.mark.parametrize(
        "category,slug",
        [
            ("user", "x"),
            ("user", "programming-preference"),
            ("user", "a1"),
            ("user_1", "slug"),
            ("user-1", "slug"),
            ("project", "deployment-env"),
            ("decision", "rag-vector-store-choice"),
            ("topic", "self-hosting"),
            ("0", "a"),
            ("a", "0"),
        ],
    )
    def test_valid_resolves_under_base(self, tmp_path: Path, category: str, slug: str) -> None:
        p = _resolve(tmp_path, category, slug)
        # 路径结束于 base/<cat>/<slug>.md
        assert p.name == f"{slug}.md"
        assert p.parent.name == category
        assert p.is_relative_to(tmp_path.resolve())

    def test_resolved_path_is_absolute(self, tmp_path: Path) -> None:
        p = _resolve(tmp_path, "user", "x")
        assert p.is_absolute()


class TestSymlinkEscape:
    """符号链接逃逸:在 tmp 下建 symlink 指向外部目录,断言拒绝。

    Windows 不支持 symlink(无权限/无开发者模式)时 skip。
    """

    @pytest.mark.skipif(
        os.name == "nt",
        reason="Windows symlink 创建通常需要管理员/开发者模式;按需 skip。",
    )
    def test_symlink_category_rejected(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        # 在 base 下创建指向外部的 symlink 目录
        base = tmp_path / "MEMORY"
        base.mkdir()
        link = base / "user"
        os.symlink(outside, link, target_is_directory=True)
        # category 合法正则通过,但 resolve 后 is_relative_to 应拒绝
        # 注意:正则允许 "user",resolve 会解 symlink,指向 outside 不在 base 内。
        with pytest.raises(ValueError):
            _resolve(base, "user", "evil")


class TestResolveIndex:
    """``resolve_index`` 固定返回 ``base/index.md``。"""

    def test_resolve_index_fixed(self, tmp_path: Path) -> None:
        p = resolve_index(tmp_path)
        assert p.name == INDEX_FILENAME
        assert p.parent == tmp_path.resolve()

    def test_resolve_index_does_not_accept_user_input(self, tmp_path: Path) -> None:
        # 无论 base 下有什么,resolve_index 不受 category/slug 影响
        p = resolve_index(tmp_path)
        assert p == tmp_path.resolve() / INDEX_FILENAME
