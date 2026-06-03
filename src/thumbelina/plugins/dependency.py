"""Plugin dependency model and metadata parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginDependency:
    """A plugin dependency declaration.

    Attributes
    ----------
    name:
        Name of the required plugin.
    version_constraint:
        Version constraint string, e.g. ">=1.0.0", "^2.0", "==1.2.3".
        Empty string means any version is acceptable.
    optional:
        If True, failure to resolve this dependency is a warning, not an error.
    """

    name: str
    version_constraint: str = ""
    optional: bool = False


@dataclass
class PluginMetadata:
    """Metadata extracted from a plugin source file.

    Attributes
    ----------
    name:
        Plugin identifier name.
    version:
        Semver version string (e.g. "1.2.3").
    description:
        Human-readable description.
    author:
        Plugin author.
    dependencies:
        List of plugin dependencies.
    conflicts:
        List of plugin names that conflict with this plugin.
    """

    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    dependencies: list[PluginDependency] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Version utilities
# ---------------------------------------------------------------------------


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a semver version string into a tuple of ints.

    Parameters
    ----------
    version:
        Version string like "1.2.3" or "1.0".

    Returns
    -------
    tuple[int, ...]
        Parsed version components, zero-padded to 3 elements.
    """
    parts = version.strip().split(".")
    nums = []
    for p in parts[:3]:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    # Pad to 3 components
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def compare_versions(v1: str, v2: str) -> int:
    """Compare two semver version strings.

    Parameters
    ----------
    v1:
        First version string.
    v2:
        Second version string.

    Returns
    -------
    int
        -1 if v1 < v2, 0 if equal, 1 if v1 > v2.
    """
    t1 = _parse_version(v1)
    t2 = _parse_version(v2)
    if t1 < t2:
        return -1
    if t1 > t2:
        return 1
    return 0


def satisfies_version(version: str, constraint: str) -> bool:
    """Check whether *version* satisfies *constraint*.

    Supported constraint formats:
    - ``">=X.Y.Z"`` — greater than or equal
    - ``">X.Y.Z"`` — strictly greater than
    - ``"<=X.Y.Z"`` — less than or equal
    - ``"<X.Y.Z"`` — strictly less than
    - ``"==X.Y.Z"`` or ``"X.Y.Z"`` — exact match
    - ``"^X.Y.Z"`` — compatible with (same major, >= specified)
    - ``""`` — any version satisfies an empty constraint

    Parameters
    ----------
    version:
        The version to test.
    constraint:
        The constraint expression.

    Returns
    -------
    bool
        True if *version* satisfies *constraint*.
    """
    constraint = constraint.strip()
    if not constraint:
        return True

    # Caret: ^1.2.3 means >=1.2.3 and <2.0.0
    if constraint.startswith("^"):
        base = constraint[1:].strip()
        base_parsed = _parse_version(base)
        ver_parsed = _parse_version(version)
        # Must be >= base and same major version
        return ver_parsed >= base_parsed and ver_parsed[0] == base_parsed[0]

    # Exact match (== prefix or bare version)
    if constraint.startswith("=="):
        target = constraint[2:].strip()
        return compare_versions(version, target) == 0

    # Inequality operators
    match = re.match(r"^(>=|<=|>|<)\s*(.+)$", constraint)
    if match:
        op, target = match.group(1), match.group(2).strip()
        cmp = compare_versions(version, target)
        if op == ">=":
            return cmp >= 0
        if op == "<=":
            return cmp <= 0
        if op == ">":
            return cmp > 0
        if op == "<":
            return cmp < 0

    # Bare version string — exact match
    return compare_versions(version, constraint) == 0


# ---------------------------------------------------------------------------
# Metadata parsing
# ---------------------------------------------------------------------------

# Docstring pattern:
#   plugin:name=foo version=1.0.0 depends=bar:>=1.0,baz conflicts=qux
_DOCSTRING_PATTERN = re.compile(
    r"plugin:"
    r"(?:.*?name=(?P<name>\S+))?"
    r"(?:.*?version=(?P<version>\S+))?"
    r"(?:.*?description=(?P<desc>[^=\n]+?))?"
    r"(?:.*?author=(?P<author>\S+))?"
    r"(?:.*?depends=(?P<deps>\S+))?"
    r"(?:.*?conflicts=(?P<conflicts>\S+))?",
    re.DOTALL,
)


def _parse_dep_string(dep_str: str) -> list[PluginDependency]:
    """Parse a comma-separated dependency string.

    Each entry is ``name`` or ``name:constraint``.
    """
    if not dep_str:
        return []
    deps: list[PluginDependency] = []
    for part in dep_str.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, constraint = part.split(":", 1)
            deps.append(PluginDependency(name=name.strip(), version_constraint=constraint.strip()))
        else:
            deps.append(PluginDependency(name=part))
    return deps


def _parse_docstring_metadata(docstring: str) -> PluginMetadata | None:
    """Try to extract metadata from a docstring containing ``plugin:`` marker."""
    match = _DOCSTRING_PATTERN.search(docstring)
    if not match:
        return None
    name = match.group("name") or ""
    if not name:
        return None
    return PluginMetadata(
        name=name,
        version=match.group("version") or "0.0.0",
        description=(match.group("desc") or "").strip(),
        author=(match.group("author") or "").strip(),
        dependencies=_parse_dep_string(match.group("deps") or ""),
        conflicts=[c.strip() for c in (match.group("conflicts") or "").split(",") if c.strip()],
    )


def _parse_dict_metadata(meta: dict[str, Any]) -> PluginMetadata:
    """Build PluginMetadata from a ``__plugin_meta__`` dict."""
    raw_deps = meta.get("dependencies", [])
    deps: list[PluginDependency] = []
    for d in raw_deps:
        if isinstance(d, str):
            deps.append(PluginDependency(name=d))
        elif isinstance(d, dict):
            deps.append(
                PluginDependency(
                    name=d.get("name", ""),
                    version_constraint=d.get("version_constraint", d.get("version", "")),
                    optional=d.get("optional", False),
                )
            )
    return PluginMetadata(
        name=meta.get("name", ""),
        version=meta.get("version", "0.0.0"),
        description=meta.get("description", ""),
        author=meta.get("author", ""),
        dependencies=deps,
        conflicts=list(meta.get("conflicts", [])),
    )


def parse_plugin_metadata(source_code: str) -> PluginMetadata:
    """Extract plugin metadata from Python source code.

    Tries two strategies in order:
    1. Look for a ``__plugin_meta__`` dict assignment.
    2. Look for a docstring containing ``plugin:`` key=value pairs.

    If neither yields metadata, returns a default :class:`PluginMetadata`
    with ``name=""`` (indicating no discoverable metadata).

    Parameters
    ----------
    source_code:
        The full source code of a plugin module.

    Returns
    -------
    PluginMetadata
        Extracted metadata, or a default with empty name.
    """
    # Strategy 1: __plugin_meta__ dict
    # We exec the source in a restricted namespace to extract the dict.
    namespace: dict[str, Any] = {}
    try:
        exec(compile(source_code, "<plugin>", "exec"), namespace)  # noqa: S102
    except Exception:
        pass

    meta_obj = namespace.get("__plugin_meta__")
    if isinstance(meta_obj, dict) and meta_obj.get("name"):
        return _parse_dict_metadata(meta_obj)

    # Strategy 2: Module-level docstring
    try:
        module = compile(source_code, "<plugin>", "exec")
        # Get the docstring from the first expression if it's a string constant
        if module.co_consts and isinstance(module.co_consts[0], str):
            docstring = module.co_consts[0]
            result = _parse_docstring_metadata(docstring)
            if result is not None:
                return result
    except Exception:
        pass

    # No metadata found — return default
    return PluginMetadata(name="")
