"""Python AST parser with FQDN extraction and import resolution."""

import ast
from pathlib import Path
from typing import Any, List, Optional, Set

from pystdoc.symbols import Parameter, Symbol


class PythonSymbolVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path, module_fqdn: str = ""):
        self.file_path = file_path
        self.module_fqdn = module_fqdn
        self.symbols: List[Symbol] = []
        self.current_scope: List[str] = [module_fqdn] if module_fqdn else []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_func(node, is_async=True)

    def _handle_func(self, node: Any, is_async: bool) -> None:
        name = node.name
        scope_str = ".".join(self.current_scope)
        fqdn = f"{scope_str}.{name}" if scope_str else name

        docstring = ast.get_docstring(node) or ""
        line_start = node.lineno
        line_end = getattr(node, "end_lineno", line_start)

        params: List[Parameter] = []
        for arg in node.args.args:
            type_hint = ast.unparse(arg.annotation) if arg.annotation else ""
            params.append(Parameter(name=arg.arg, type_hint=type_hint))

        return_type = ast.unparse(node.returns) if node.returns else ""

        callee_visitor = CalleeVisitor()
        callee_visitor.visit(node)

        sym = Symbol(
            name=name,
            kind="async_function" if is_async else "function",
            line_start=line_start,
            line_end=line_end,
            fqdn=fqdn,
            signature=f"def {name}(...)",
            doc=docstring,
            parameters=params,
            return_type=return_type,
            callees=sorted(list(callee_visitor.callees)),
        )
        self.symbols.append(sym)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        name = node.name
        scope_str = ".".join(self.current_scope)
        fqdn = f"{scope_str}.{name}" if scope_str else name

        docstring = ast.get_docstring(node) or ""
        line_start = node.lineno
        line_end = getattr(node, "end_lineno", line_start)

        self.current_scope.append(name)
        child_visitor = PythonSymbolVisitor(self.file_path, module_fqdn=fqdn)
        for item in node.body:
            child_visitor.visit(item)
        self.current_scope.pop()

        sym = Symbol(
            name=name,
            kind="class",
            line_start=line_start,
            line_end=line_end,
            fqdn=fqdn,
            signature=f"class {name}",
            doc=docstring,
            children=child_visitor.symbols,
        )
        self.symbols.append(sym)


class CalleeVisitor(ast.NodeVisitor):
    def __init__(self):
        self.callees: Set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.callees.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.callees.add(node.func.attr)
        self.generic_visit(node)


def parse_python_file(
    file_path: Path, base_dir: Optional[Path] = None
) -> List[Symbol]:
    """Parse a Python source file using AST and attach clean FQDNs."""
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))

        try:
            if base_dir:
                rel = file_path.relative_to(base_dir)
            elif "src" in file_path.parts:
                src_idx = file_path.parts.index("src")
                rel = Path(*file_path.parts[src_idx:])
            else:
                rel = Path(file_path.name)
            parts = rel.with_suffix("").parts
            mod_fqdn = ".".join(parts)
        except Exception:
            mod_fqdn = file_path.stem

        visitor = PythonSymbolVisitor(file_path, module_fqdn=mod_fqdn)
        visitor.visit(tree)
        return visitor.symbols
    except Exception:
        return []
