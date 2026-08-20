"""Import-level architecture guardrails.

These checks intentionally use the AST rather than an allow-list in CI so a
new direct import cannot quietly reopen an adapter boundary.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        ("api", "src.storage"),
        ("api", "src.observability"),
        ("runtime", "src.api"),
        ("runtime", "src.observability"),
        ("runtime", "src.models.gateway"),
        ("harness", "src.api"),
        ("harness", "src.models.gateway"),
    ],
)
def test_dependency_direction_is_preserved(package: str, forbidden: str) -> None:
    violations: list[str] = []
    for path in sorted((SRC_ROOT / package).rglob("*.py")):
        for module in _imports(path):
            if module == forbidden or module.startswith(f"{forbidden}."):
                violations.append(f"{path.relative_to(SRC_ROOT)} -> {module}")
    assert not violations, "\n".join(violations)


def test_runtime_state_compatibility_aliases_harness_contract() -> None:
    from src.harness.contracts.state import AgentState as HarnessAgentState
    from src.runtime.state import AgentState as LegacyAgentState

    assert LegacyAgentState is HarnessAgentState


def test_production_code_does_not_depend_on_legacy_kb_namespace() -> None:
    """Knowledge code lives in the capability tree, not the removed legacy package."""
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path.is_relative_to(SRC_ROOT / "kb"):
            continue
        for module in _imports(path):
            if module == "src.kb" or module.startswith("src.kb."):
                violations.append(f"{path.relative_to(SRC_ROOT)} -> {module}")
    assert not violations, "\n".join(violations)


def test_production_code_does_not_depend_on_legacy_memory_namespace() -> None:
    """Memory code lives in the capability tree, not the removed legacy package."""
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path.is_relative_to(SRC_ROOT / "memory"):
            continue
        for module in _imports(path):
            if module == "src.memory" or module.startswith("src.memory."):
                violations.append(f"{path.relative_to(SRC_ROOT)} -> {module}")
    assert not violations, "\n".join(violations)


def test_production_code_does_not_depend_on_legacy_planning_namespace() -> None:
    """Task planning is owned by the harness orchestration package."""
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path.is_relative_to(SRC_ROOT / "planning"):
            continue
        for module in _imports(path):
            if module == "src.planning" or module.startswith("src.planning."):
                violations.append(f"{path.relative_to(SRC_ROOT)} -> {module}")
    assert not violations, "\n".join(violations)


def test_production_code_does_not_depend_on_removed_settings_user_namespace() -> None:
    """User provider configuration belongs to the settings capability."""
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        for module in _imports(path):
            if module == "src.settings_user" or module.startswith("src.settings_user."):
                violations.append(f"{path.relative_to(SRC_ROOT)} -> {module}")
    assert not violations, "\n".join(violations)
