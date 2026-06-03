"""Tests for plugin dependency resolution."""

from __future__ import annotations

import textwrap

import pytest

from thumbelina.plugins.dependency import (
    PluginDependency,
    PluginMetadata,
    compare_versions,
    parse_plugin_metadata,
    satisfies_version,
)
from thumbelina.plugins.resolver import DependencyResolver


# ---------------------------------------------------------------------------
# Metadata parsing tests
# ---------------------------------------------------------------------------


class TestParseMetadataDocstring:
    """Test metadata extraction from docstrings."""

    def test_parse_docstring_basic(self):
        """Should parse basic docstring metadata."""
        source = textwrap.dedent('''\
            """plugin:name=foo version=1.0.0 description=My plugin author=Alice"""
            pass
        ''')
        meta = parse_plugin_metadata(source)
        assert meta.name == "foo"
        assert meta.version == "1.0.0"
        assert meta.author == "Alice"

    def test_parse_docstring_with_dependencies(self):
        """Should parse dependencies from docstring."""
        source = textwrap.dedent('''\
            """plugin:name=bar version=2.0.0 depends=baz:>=1.0,qux"""
            pass
        ''')
        meta = parse_plugin_metadata(source)
        assert meta.name == "bar"
        assert meta.version == "2.0.0"
        assert len(meta.dependencies) == 2
        assert meta.dependencies[0].name == "baz"
        assert meta.dependencies[0].version_constraint == ">=1.0"
        assert meta.dependencies[1].name == "qux"
        assert meta.dependencies[1].version_constraint == ""

    def test_parse_docstring_with_conflicts(self):
        """Should parse conflicts from docstring."""
        source = textwrap.dedent('''\
            """plugin:name=foo version=1.0.0 conflicts=bar,baz"""
            pass
        ''')
        meta = parse_plugin_metadata(source)
        assert meta.conflicts == ["bar", "baz"]


class TestParseMetadataDict:
    """Test metadata extraction from __plugin_meta__ dict."""

    def test_parse_dict_basic(self):
        """Should parse __plugin_meta__ dict."""
        source = textwrap.dedent('''\
            __plugin_meta__ = {
                "name": "my_plugin",
                "version": "3.1.0",
                "description": "A test plugin",
                "author": "Bob",
            }
        ''')
        meta = parse_plugin_metadata(source)
        assert meta.name == "my_plugin"
        assert meta.version == "3.1.0"
        assert meta.description == "A test plugin"
        assert meta.author == "Bob"

    def test_parse_dict_with_dependencies_as_strings(self):
        """Should parse string dependencies from dict."""
        source = textwrap.dedent('''\
            __plugin_meta__ = {
                "name": "child",
                "version": "1.0.0",
                "dependencies": ["parent", "helper"],
            }
        ''')
        meta = parse_plugin_metadata(source)
        assert len(meta.dependencies) == 2
        assert meta.dependencies[0].name == "parent"
        assert meta.dependencies[1].name == "helper"

    def test_parse_dict_with_dependencies_as_dicts(self):
        """Should parse dict dependencies with constraints."""
        source = textwrap.dedent('''\
            __plugin_meta__ = {
                "name": "child",
                "version": "1.0.0",
                "dependencies": [
                    {"name": "parent", "version_constraint": ">=2.0.0"},
                    {"name": "optional_dep", "optional": True},
                ],
            }
        ''')
        meta = parse_plugin_metadata(source)
        assert len(meta.dependencies) == 2
        assert meta.dependencies[0].name == "parent"
        assert meta.dependencies[0].version_constraint == ">=2.0.0"
        assert meta.dependencies[1].name == "optional_dep"
        assert meta.dependencies[1].optional is True

    def test_parse_dict_with_conflicts(self):
        """Should parse conflicts from dict."""
        source = textwrap.dedent('''\
            __plugin_meta__ = {
                "name": "conflicting",
                "version": "1.0.0",
                "conflicts": ["other_plugin"],
            }
        ''')
        meta = parse_plugin_metadata(source)
        assert meta.conflicts == ["other_plugin"]


class TestParseMetadataGraceful:
    """Test graceful handling of missing metadata."""

    def test_no_metadata_returns_empty_name(self):
        """Should return PluginMetadata with empty name when no metadata found."""
        source = "x = 42\n"
        meta = parse_plugin_metadata(source)
        assert meta.name == ""

    def test_empty_source(self):
        """Should handle empty source gracefully."""
        meta = parse_plugin_metadata("")
        assert meta.name == ""

    def test_syntax_error_source(self):
        """Should handle syntax errors gracefully."""
        source = "def foo(:\n"
        meta = parse_plugin_metadata(source)
        assert meta.name == ""

    def test_dict_without_name(self):
        """Dict without 'name' key should fall through to docstring check."""
        source = textwrap.dedent('''\
            __plugin_meta__ = {
                "version": "1.0.0",
            }
        ''')
        meta = parse_plugin_metadata(source)
        # __plugin_meta__ has no name, so should fall through
        assert meta.name == ""


# ---------------------------------------------------------------------------
# Version comparison tests
# ---------------------------------------------------------------------------


class TestCompareVersions:
    """Test compare_versions utility."""

    def test_equal_versions(self):
        """Equal versions should return 0."""
        assert compare_versions("1.0.0", "1.0.0") == 0

    def test_greater_version(self):
        """Greater version should return 1."""
        assert compare_versions("2.0.0", "1.0.0") == 1

    def test_lesser_version(self):
        """Lesser version should return -1."""
        assert compare_versions("1.0.0", "2.0.0") == -1

    def test_patch_difference(self):
        """Should compare patch versions."""
        assert compare_versions("1.0.1", "1.0.0") == 1
        assert compare_versions("1.0.0", "1.0.1") == -1

    def test_major_minor_difference(self):
        """Should compare major.minor versions."""
        assert compare_versions("1.2.0", "1.1.0") == 1

    def test_short_version_padded(self):
        """Short versions should be zero-padded."""
        assert compare_versions("1.0", "1.0.0") == 0
        assert compare_versions("2", "2.0.0") == 0


class TestSatisfiesVersion:
    """Test satisfies_version constraint checking."""

    def test_empty_constraint(self):
        """Empty constraint should match any version."""
        assert satisfies_version("1.0.0", "") is True
        assert satisfies_version("99.99.99", "") is True

    def test_exact_match(self):
        """== constraint should match exact version."""
        assert satisfies_version("1.2.3", "==1.2.3") is True
        assert satisfies_version("1.2.4", "==1.2.3") is False

    def test_bare_version_exact(self):
        """Bare version string should be exact match."""
        assert satisfies_version("1.0.0", "1.0.0") is True
        assert satisfies_version("1.0.1", "1.0.0") is False

    def test_gte_constraint(self):
        """>= constraint should match greater or equal."""
        assert satisfies_version("1.0.0", ">=1.0.0") is True
        assert satisfies_version("2.0.0", ">=1.0.0") is True
        assert satisfies_version("0.9.0", ">=1.0.0") is False

    def test_gt_constraint(self):
        """> constraint should match strictly greater."""
        assert satisfies_version("1.0.1", ">1.0.0") is True
        assert satisfies_version("1.0.0", ">1.0.0") is False

    def test_lte_constraint(self):
        """<= constraint should match less or equal."""
        assert satisfies_version("1.0.0", "<=1.0.0") is True
        assert satisfies_version("0.9.0", "<=1.0.0") is True
        assert satisfies_version("1.0.1", "<=1.0.0") is False

    def test_lt_constraint(self):
        """< constraint should match strictly less."""
        assert satisfies_version("0.9.9", "<1.0.0") is True
        assert satisfies_version("1.0.0", "<1.0.0") is False

    def test_caret_constraint(self):
        """^ constraint should match same major, >= specified."""
        assert satisfies_version("1.2.0", "^1.0.0") is True
        assert satisfies_version("1.9.9", "^1.0.0") is True
        assert satisfies_version("2.0.0", "^1.0.0") is False
        assert satisfies_version("0.9.0", "^1.0.0") is False


# ---------------------------------------------------------------------------
# Dependency resolver tests
# ---------------------------------------------------------------------------


class TestDependencyResolver:
    """Test the DependencyResolver topological sort and validation."""

    @pytest.fixture
    def resolver(self):
        return DependencyResolver()

    def test_simple_chain(self, resolver):
        """Simple A -> B -> C chain should produce [C, B, A] order."""
        plugins = {
            "A": PluginMetadata(
                name="A", version="1.0.0",
                dependencies=[PluginDependency(name="B")],
            ),
            "B": PluginMetadata(
                name="B", version="1.0.0",
                dependencies=[PluginDependency(name="C")],
            ),
            "C": PluginMetadata(name="C", version="1.0.0"),
        }
        load_order, errors = resolver.resolve(plugins)
        assert not errors
        # C must come before B, B before A
        assert load_order.index("C") < load_order.index("B")
        assert load_order.index("B") < load_order.index("A")

    def test_diamond_dependency(self, resolver):
        """Diamond: A -> B, A -> C, B -> D, C -> D."""
        plugins = {
            "A": PluginMetadata(
                name="A", version="1.0.0",
                dependencies=[
                    PluginDependency(name="B"),
                    PluginDependency(name="C"),
                ],
            ),
            "B": PluginMetadata(
                name="B", version="1.0.0",
                dependencies=[PluginDependency(name="D")],
            ),
            "C": PluginMetadata(
                name="C", version="1.0.0",
                dependencies=[PluginDependency(name="D")],
            ),
            "D": PluginMetadata(name="D", version="1.0.0"),
        }
        load_order, errors = resolver.resolve(plugins)
        assert not errors
        # D must be loaded first
        assert load_order.index("D") < load_order.index("B")
        assert load_order.index("D") < load_order.index("C")
        assert load_order.index("B") < load_order.index("A")
        assert load_order.index("C") < load_order.index("A")

    def test_circular_dependency_detected(self, resolver):
        """Circular A -> B -> A should be detected."""
        plugins = {
            "A": PluginMetadata(
                name="A", version="1.0.0",
                dependencies=[PluginDependency(name="B")],
            ),
            "B": PluginMetadata(
                name="B", version="1.0.0",
                dependencies=[PluginDependency(name="A")],
            ),
        }
        load_order, errors = resolver.resolve(plugins)
        assert len(load_order) < 2
        assert any("Circular" in e or "circular" in e for e in errors)

    def test_missing_dependency_detected(self, resolver):
        """Missing dependency should be reported."""
        plugins = {
            "A": PluginMetadata(
                name="A", version="1.0.0",
                dependencies=[PluginDependency(name="nonexistent")],
            ),
        }
        _load_order, errors = resolver.resolve(plugins)
        assert any("nonexistent" in e and "not available" in e for e in errors)

    def test_conflict_detection(self, resolver):
        """Conflicting plugins should be detected."""
        plugins = {
            "A": PluginMetadata(
                name="A", version="1.0.0",
                conflicts=["B"],
            ),
            "B": PluginMetadata(name="B", version="1.0.0"),
        }
        errors = resolver.check_conflicts(plugins)
        assert len(errors) == 1
        assert "conflicts" in errors[0].lower()
        assert "A" in errors[0] and "B" in errors[0]

    def test_optional_dependency_handled(self, resolver):
        """Optional missing dependency should be a warning, not block loading."""
        plugins = {
            "A": PluginMetadata(
                name="A", version="1.0.0",
                dependencies=[
                    PluginDependency(name="optional_dep", optional=True),
                ],
            ),
        }
        load_order, errors = resolver.resolve(plugins)
        # A should still be in the load order
        assert "A" in load_order
        # Optional missing dep should be reported as info/warning
        assert any("optional_dep" in e and "Optional" in e for e in errors)

    def test_no_dependencies(self, resolver):
        """Plugin with no dependencies should load fine."""
        plugins = {
            "solo": PluginMetadata(name="solo", version="1.0.0"),
        }
        load_order, errors = resolver.resolve(plugins)
        assert not errors
        assert load_order == ["solo"]

    def test_multiple_independent_plugins(self, resolver):
        """Multiple independent plugins should all appear in load order."""
        plugins = {
            "A": PluginMetadata(name="A", version="1.0.0"),
            "B": PluginMetadata(name="B", version="1.0.0"),
            "C": PluginMetadata(name="C", version="1.0.0"),
        }
        load_order, errors = resolver.resolve(plugins)
        assert not errors
        assert set(load_order) == {"A", "B", "C"}

    def test_version_constraint_satisfied(self, resolver):
        """When version constraint is met, no error should be raised."""
        plugins = {
            "lib": PluginMetadata(name="lib", version="2.0.0"),
            "app": PluginMetadata(
                name="app", version="1.0.0",
                dependencies=[
                    PluginDependency(name="lib", version_constraint=">=1.0.0"),
                ],
            ),
        }
        _load_order, errors = resolver.resolve(plugins)
        version_errors = [e for e in errors if "requires" in e and "but found" in e]
        assert len(version_errors) == 0

    def test_version_constraint_unsatisfied(self, resolver):
        """When version constraint is not met, an error should be raised."""
        plugins = {
            "lib": PluginMetadata(name="lib", version="0.5.0"),
            "app": PluginMetadata(
                name="app", version="1.0.0",
                dependencies=[
                    PluginDependency(name="lib", version_constraint=">=1.0.0"),
                ],
            ),
        }
        _load_order, errors = resolver.resolve(plugins)
        assert any("requires" in e and "but found" in e for e in errors)

    def test_complex_graph_load_order(self, resolver):
        """Complex dependency graph should produce valid topological order."""
        # A -> B, A -> C, B -> D, C -> D, D -> E
        plugins = {
            "A": PluginMetadata(
                name="A", version="1.0.0",
                dependencies=[
                    PluginDependency(name="B"),
                    PluginDependency(name="C"),
                ],
            ),
            "B": PluginMetadata(
                name="B", version="1.0.0",
                dependencies=[PluginDependency(name="D")],
            ),
            "C": PluginMetadata(
                name="C", version="1.0.0",
                dependencies=[PluginDependency(name="D")],
            ),
            "D": PluginMetadata(
                name="D", version="1.0.0",
                dependencies=[PluginDependency(name="E")],
            ),
            "E": PluginMetadata(name="E", version="1.0.0"),
        }
        load_order, errors = resolver.resolve(plugins)
        assert not errors
        assert len(load_order) == 5
        # Validate ordering constraints
        assert load_order.index("E") < load_order.index("D")
        assert load_order.index("D") < load_order.index("B")
        assert load_order.index("D") < load_order.index("C")
        assert load_order.index("B") < load_order.index("A")
        assert load_order.index("C") < load_order.index("A")

    def test_three_way_circular(self, resolver):
        """Three-way circular dependency A -> B -> C -> A should be detected."""
        plugins = {
            "A": PluginMetadata(
                name="A", version="1.0.0",
                dependencies=[PluginDependency(name="B")],
            ),
            "B": PluginMetadata(
                name="B", version="1.0.0",
                dependencies=[PluginDependency(name="C")],
            ),
            "C": PluginMetadata(
                name="C", version="1.0.0",
                dependencies=[PluginDependency(name="A")],
            ),
        }
        load_order, errors = resolver.resolve(plugins)
        assert len(load_order) < 3
        assert any("Circular" in e or "circular" in e for e in errors)

    def test_empty_plugins(self, resolver):
        """Empty plugin set should return empty results."""
        load_order, errors = resolver.resolve({})
        assert load_order == []
        assert errors == []

    def test_dependency_with_caret_version(self, resolver):
        """Caret version constraint should work with resolver."""
        plugins = {
            "lib": PluginMetadata(name="lib", version="1.5.0"),
            "app": PluginMetadata(
                name="app", version="1.0.0",
                dependencies=[
                    PluginDependency(name="lib", version_constraint="^1.0.0"),
                ],
            ),
        }
        load_order, errors = resolver.resolve(plugins)
        version_errors = [e for e in errors if "requires" in e and "but found" in e]
        assert len(version_errors) == 0
        assert "lib" in load_order
        assert "app" in load_order


# ---------------------------------------------------------------------------
# PluginDependency and PluginMetadata dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    """Test dataclass creation and defaults."""

    def test_plugin_dependency_defaults(self):
        """PluginDependency should have sensible defaults."""
        dep = PluginDependency(name="foo")
        assert dep.name == "foo"
        assert dep.version_constraint == ""
        assert dep.optional is False

    def test_plugin_metadata_defaults(self):
        """PluginMetadata should have sensible defaults."""
        meta = PluginMetadata(name="bar")
        assert meta.name == "bar"
        assert meta.version == "0.0.0"
        assert meta.description == ""
        assert meta.author == ""
        assert meta.dependencies == []
        assert meta.conflicts == []
