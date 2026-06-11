"""Architecture invariant tests for the finstore package.

Rules enforced here:
  1. finstore.* may not import finstore_local.*
  2. finstore.model.* and finstore.storage.* may not import finstore.backends.*
  3. Outside finstore.backends.simplefin.*, no module may import
     finstore.backends.simplefin.models (the Sf* types).
  5. finstore_local.web.* may not import from gateway.*
  6. No public symbol in finstore.* references Sf* or finstore_local.* types.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).parent.parent.parent / "src"


def _collect_imports(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _add_with_prefixes(modules, alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                _add_with_prefixes(modules, node.module)
                for alias in node.names:
                    if alias.name != "*":
                        _add_with_prefixes(modules, f"{node.module}.{alias.name}")
    return modules


def _add_with_prefixes(modules: set[str], dotted: str) -> None:
    parts = dotted.split(".")
    for i in range(1, len(parts) + 1):
        modules.add(".".join(parts[:i]))


def _collect_imports_for_package(package_path: Path) -> dict[Path, set[str]]:
    result: dict[Path, set[str]] = {}
    for py_file in sorted(package_path.rglob("*.py")):
        result[py_file] = _collect_imports(py_file)
    return result


def _assert_no_forbidden(
    imports_by_file: dict[Path, set[str]],
    forbidden: set[str],
    label: str,
) -> None:
    violations: list[str] = []
    for path, imports in imports_by_file.items():
        found = imports & forbidden
        if found:
            violations.append(f"  {path.relative_to(SRC_ROOT)}: imports {sorted(found)}")
    assert not violations, (
        f"{label} — forbidden import(s) found:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 1: finstore.* may not import finstore_local.*
# ---------------------------------------------------------------------------


def test_finstore_does_not_import_finstore_local() -> None:
    finstore_dir = SRC_ROOT / "finstore"
    imports_by_file = _collect_imports_for_package(finstore_dir)
    _assert_no_forbidden(imports_by_file, {"finstore_local"}, "finstore")


# ---------------------------------------------------------------------------
# Rule 2: finstore.model.* and finstore.storage.* may not import finstore.backends.*
# ---------------------------------------------------------------------------


def test_finstore_model_does_not_import_backends() -> None:
    model_dir = SRC_ROOT / "finstore" / "model"
    imports_by_file = _collect_imports_for_package(model_dir)
    _assert_no_forbidden(imports_by_file, {"finstore.backends"}, "finstore.model")


def test_finstore_storage_does_not_import_backends() -> None:
    storage_dir = SRC_ROOT / "finstore" / "storage"
    imports_by_file = _collect_imports_for_package(storage_dir)
    _assert_no_forbidden(imports_by_file, {"finstore.backends"}, "finstore.storage")


# ---------------------------------------------------------------------------
# Rule 3: outside finstore.backends.simplefin.*, no Sf-model import
# ---------------------------------------------------------------------------


def test_simplefin_models_only_imported_inside_simplefin_package() -> None:
    simplefin_dir = SRC_ROOT / "finstore" / "backends" / "simplefin"

    violations: list[str] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        try:
            py_file.relative_to(simplefin_dir)
        except ValueError:
            pass
        else:
            continue
        imports = _collect_imports(py_file)
        if "finstore.backends.simplefin.models" in imports:
            violations.append(str(py_file.relative_to(SRC_ROOT)))

    assert not violations, (
        "finstore.backends.simplefin.models must only be imported inside "
        "finstore.backends.simplefin.*. Violations:\n  " + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 5: finstore_local.web.* may not import from gateway.*
# ---------------------------------------------------------------------------


def test_finstore_local_web_does_not_import_gateway() -> None:
    web_dir = SRC_ROOT / "finstore_local" / "web"
    imports_by_file = _collect_imports_for_package(web_dir)
    _assert_no_forbidden(imports_by_file, {"gateway"}, "finstore_local.web")


# ---------------------------------------------------------------------------
# Rule 6: no public symbol references Sf* or finstore_local.* types
# ---------------------------------------------------------------------------


def test_public_surface_has_no_sf_or_finstore_local_types() -> None:
    import importlib

    public_modules = [
        "finstore",
        "finstore.model",
        "finstore.protocols",
        "finstore.storage",
        "finstore.backends.simplefin",
    ]
    violations: list[str] = []

    for mod_name in public_modules:
        mod = importlib.import_module(mod_name)
        for name in getattr(mod, "__all__", []):
            obj = getattr(mod, name)
            obj_mod = getattr(obj, "__module__", "")
            if name.startswith("Sf"):
                violations.append(f"{mod_name}.{name}: name starts with 'Sf'")
            if obj_mod.startswith("finstore_local"):
                violations.append(
                    f"{mod_name}.{name}: defined in {obj_mod} (finstore_local.* is private)"
                )
            if obj_mod.startswith("finstore.backends.simplefin.models"):
                violations.append(
                    f"{mod_name}.{name}: defined in {obj_mod} (Sf* types are backend-internal)"
                )

    assert not violations, (
        "Public surface contains forbidden references:\n  " + "\n  ".join(violations)
    )
