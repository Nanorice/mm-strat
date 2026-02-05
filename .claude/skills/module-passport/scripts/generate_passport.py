#!/usr/bin/env python3
"""
Module Passport Generator
Analyzes Python modules and generates technical documentation.
"""

import ast
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple


class ModuleInfo(NamedTuple):
    name: str
    root: Path
    files: list[Path]


class ExtractedData(NamedTuple):
    schemas: list[dict]
    constants: list[dict]
    public_api: list[dict]
    imports: dict[str, list[str]]  # file -> list of local imports


def resolve_module(entry_point: str) -> ModuleInfo:
    """Resolve module root and name from any file path within it."""
    path = Path(entry_point).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Entry point not found: {entry_point}")

    module_root = path.parent
    module_name = module_root.name

    # Collect all .py files, skip __init__ and test files
    py_files = []
    for f in module_root.rglob("*.py"):
        if f.name == "__init__.py":
            continue
        if "test" in f.parts or f.name.startswith("test_"):
            continue
        py_files.append(f)

    return ModuleInfo(name=module_name, root=module_root, files=sorted(py_files))


def extract_from_file(filepath: Path, module_root: Path) -> ExtractedData:
    """Extract schemas, constants, and API from a single file."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"[WARN] Could not parse {filepath}: {e}")
        return ExtractedData([], [], [], {})

    schemas = []
    constants = []
    public_api = []
    local_imports = []

    rel_path = filepath.relative_to(module_root)
    file_key = str(rel_path.with_suffix("")).replace(os.sep, ".")

    for node in ast.walk(tree):
        # Extract TypedDict / dataclass
        if isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                # Check for TypedDict or dataclass
                is_schema = False
                bases = [_get_name(b) for b in node.bases]
                decorators = [_get_name(d) for d in node.decorator_list]

                if "TypedDict" in bases:
                    is_schema = True
                    schema_type = "TypedDict"
                elif "dataclass" in decorators:
                    is_schema = True
                    schema_type = "dataclass"

                if is_schema:
                    fields = _extract_class_fields(node)
                    schemas.append({
                        "name": node.name,
                        "type": schema_type,
                        "fields": fields,
                        "file": file_key
                    })
                else:
                    # Public class - extract methods
                    methods = _extract_public_methods(node)
                    public_api.append({
                        "kind": "class",
                        "name": node.name,
                        "methods": methods,
                        "file": file_key,
                        "line": node.lineno
                    })

        # Extract public functions
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            # Only top-level functions (not methods)
            if _is_top_level(tree, node):
                sig = _get_function_signature(node)
                public_api.append({
                    "kind": "function",
                    "name": node.name,
                    "signature": sig,
                    "file": file_key,
                    "line": node.lineno
                })

        # Extract UPPERCASE constants
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    value = _get_constant_value(node.value)
                    constants.append({
                        "name": target.id,
                        "value": value,
                        "file": file_key
                    })

        # Extract local imports for dependency graph
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Check if it's a local import
                if not node.module.startswith(("os", "sys", "typing", "pathlib",
                    "datetime", "collections", "json", "re", "ast", "functools",
                    "itertools", "dataclasses", "enum", "abc", "copy", "math",
                    "pandas", "numpy", "sqlalchemy")):
                    local_imports.append(node.module.split(".")[0])

    return ExtractedData(
        schemas=schemas,
        constants=constants,
        public_api=public_api,
        imports={file_key: local_imports}
    )


def _get_name(node) -> str:
    """Get name from AST node."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Call):
        return _get_name(node.func)
    return ""


def _extract_class_fields(node: ast.ClassDef) -> list[dict]:
    """Extract fields from TypedDict or dataclass."""
    fields = []
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            field_type = ast.unparse(item.annotation) if item.annotation else "Any"
            fields.append({"name": item.target.id, "type": field_type})
    return fields


def _extract_public_methods(node: ast.ClassDef) -> list[str]:
    """Extract public method names from a class."""
    methods = []
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
            sig = _get_function_signature(item)
            methods.append(f"{item.name}{sig}")
    return methods


def _get_function_signature(node: ast.FunctionDef) -> str:
    """Get function signature string."""
    args = []
    for arg in node.args.args:
        if arg.arg == "self":
            continue
        annotation = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        args.append(f"{arg.arg}{annotation}")

    returns = ""
    if node.returns:
        returns = f" -> {ast.unparse(node.returns)}"

    return f"({', '.join(args)}){returns}"


def _get_constant_value(node) -> str:
    """Get string representation of constant value."""
    try:
        if isinstance(node, ast.Constant):
            val = repr(node.value)
            return val[:50] + "..." if len(val) > 50 else val
        return ast.unparse(node)[:50]
    except Exception:
        return "<complex>"


def _is_top_level(tree: ast.Module, func_node: ast.FunctionDef) -> bool:
    """Check if function is defined at module level."""
    return func_node in tree.body


def generate_markdown(module: ModuleInfo, data: ExtractedData) -> str:
    """Generate the passport markdown content."""
    lines = [
        f"# Module: {module.name}",
        "",
        "## 1. Overview",
        "",
        f"**Location:** `{module.root}`",
        f"**Files:** {len(module.files)}",
        "",
    ]

    # Visual Architecture (Mermaid)
    lines.extend([
        "## 2. Visual Architecture",
        "",
        "```mermaid",
        "graph TD",
    ])

    # Build dependency graph from imports
    all_files = {str(f.relative_to(module.root).with_suffix("")).replace(os.sep, ".")
                 for f in module.files}
    for file_key, imports in data.imports.items():
        safe_key = file_key.replace(".", "_")
        lines.append(f"    {safe_key}[{file_key}]")
        for imp in imports:
            if imp in all_files or any(imp in f for f in all_files):
                safe_imp = imp.replace(".", "_")
                lines.append(f"    {safe_key} --> {safe_imp}")

    lines.extend(["```", ""])

    # Data Schemas
    lines.extend(["## 3. Data Schemas", ""])
    if data.schemas:
        for schema in data.schemas:
            lines.append(f"### {schema['name']} ({schema['type']})")
            lines.append(f"*Defined in: `{schema['file']}`*")
            lines.append("")
            if schema["fields"]:
                lines.append("| Field | Type |")
                lines.append("|-------|------|")
                for field in schema["fields"]:
                    lines.append(f"| `{field['name']}` | `{field['type']}` |")
            lines.append("")
    else:
        lines.append("*No TypedDict or dataclass schemas detected.*")
        lines.append("")

    # Implementation Rules (Constants)
    lines.extend(["## 4. Implementation Rules", ""])
    if data.constants:
        lines.append("| Constant | Value | File |")
        lines.append("|----------|-------|------|")
        for const in data.constants:
            lines.append(f"| `{const['name']}` | `{const['value']}` | `{const['file']}` |")
        lines.append("")
    else:
        lines.append("*No module-level constants detected.*")
        lines.append("")

    # Public Interface
    lines.extend(["## 5. Public Interface", ""])
    if data.public_api:
        # Group by file
        by_file: dict[str, list] = {}
        for item in data.public_api:
            by_file.setdefault(item["file"], []).append(item)

        for file_key, items in sorted(by_file.items()):
            lines.append(f"### `{file_key}`")
            lines.append("")
            for item in items:
                if item["kind"] == "class":
                    lines.append(f"**class {item['name']}**")
                    if item["methods"]:
                        for method in item["methods"]:
                            lines.append(f"  - `{method}`")
                else:
                    lines.append(f"- `{item['name']}{item['signature']}`")
            lines.append("")
    else:
        lines.append("*No public API detected.*")
        lines.append("")

    # Maintenance Log
    lines.extend([
        "## 6. Maintenance Log",
        "",
        f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d')}",
        ""
    ])

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_passport.py <entry_point_path>")
        sys.exit(1)

    entry_point = sys.argv[1]

    # Resolve module
    module = resolve_module(entry_point)
    print(f"[OK] Module: {module.name} ({len(module.files)} files)")

    # Extract data from all files
    all_schemas = []
    all_constants = []
    all_api = []
    all_imports = {}

    for filepath in module.files:
        extracted = extract_from_file(filepath, module.root)
        all_schemas.extend(extracted.schemas)
        all_constants.extend(extracted.constants)
        all_api.extend(extracted.public_api)
        all_imports.update(extracted.imports)

    combined = ExtractedData(
        schemas=all_schemas,
        constants=all_constants,
        public_api=all_api,
        imports=all_imports
    )

    # Generate markdown
    content = generate_markdown(module, combined)

    # Ensure output directory exists
    output_dir = Path("docs/modules")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{module.name}.md"
    output_path.write_text(content, encoding="utf-8")

    print(f"Updated {module.name} passport at {output_path}. Detected {len(module.files)} files.")


if __name__ == "__main__":
    main()
