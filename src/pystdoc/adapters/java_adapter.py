"""Java language adapter using javalang AST parser."""

from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

import javalang
import javalang.tree

from pystdoc.adapters.base import (
    BaseLanguageAdapter,
    build_fqdn,
    calculate_block_end_line,
    clean_docstring,
)
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.symbols import Parameter, Symbol


def _format_type(type_node: Any) -> str:
    """Format javalang type node into a clean string representation."""
    if type_node is None:
        return "void"
    if isinstance(type_node, str):
        return type_node
    name = getattr(type_node, "name", "")
    type_args = getattr(type_node, "arguments", None)
    args_str = ""
    if type_args:
        args_parts = []
        for arg in type_args:
            if hasattr(arg, "type"):
                args_parts.append(_format_type(arg.type))
            elif hasattr(arg, "name"):
                args_parts.append(arg.name)
            else:
                args_parts.append(str(arg))
        if args_parts:
            args_str = f"<{', '.join(args_parts)}>"
    dims = getattr(type_node, "dimensions", None)
    dims_str = "[]" * len(dims) if dims else ""
    sub_type = getattr(type_node, "sub_type", None)
    sub_str = f".{_format_type(sub_type)}" if sub_type else ""
    return f"{name}{args_str}{dims_str}{sub_str}"


def _extract_java_callees(node: Any) -> List[str]:
    """Extract call and instantiation names from a Java AST node."""
    callees: Set[str] = set()
    if node is None or not hasattr(node, "filter"):
        return []

    for _, inv in node.filter(javalang.tree.MethodInvocation):
        if inv.member:
            callees.add(inv.member)
    for _, creator in node.filter(javalang.tree.ClassCreator):
        if creator.type and hasattr(creator.type, "name"):
            callees.add(creator.type.name)
    for _, exp in node.filter(javalang.tree.ExplicitConstructorInvocation):
        if getattr(exp, "qualifier", None):
            callees.add(str(exp.qualifier))
        else:
            callees.add("this")
    for _, exp in node.filter(javalang.tree.SuperConstructorInvocation):
        if getattr(exp, "qualifier", None):
            callees.add(str(exp.qualifier))
        else:
            callees.add("super")
    return sorted(list(callees))


class JavaAdapter(BaseLanguageAdapter):
    """Adapter for Java source files using javalang AST."""

    @property
    def name(self) -> str:
        return "java"

    @property
    def supported_extensions(self) -> Tuple[str, ...]:
        return (".java",)

    @property
    def default_code_language(self) -> str:
        return "java"

    def parse(
        self,
        file_path: Path,
        comp_db: Optional[CompilationDatabase] = None,
        base_dir: Optional[Path] = None,
    ) -> List[Symbol]:
        """Parse Java file and return hierarchical Symbol list."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            source_lines = content.splitlines()
            tree = javalang.parse.parse(content)
        except Exception:
            return []

        package_name = tree.package.name if tree.package else ""
        file_prefix = file_path.stem
        scope_prefix = package_name if package_name else file_prefix

        symbols: List[Symbol] = []
        for type_decl in tree.types:
            sym = self._parse_type_declaration(
                type_decl, source_lines, [scope_prefix]
            )
            if sym:
                symbols.append(sym)

        return symbols

    def _parse_type_declaration(
        self,
        node: Any,
        source_lines: List[str],
        scope_stack: List[str],
    ) -> Optional[Symbol]:
        name = getattr(node, "name", "")
        if not name:
            return None

        if isinstance(node, javalang.tree.EnumDeclaration):
            kind = "enum"
        elif isinstance(node, javalang.tree.InterfaceDeclaration):
            kind = "class"
        elif isinstance(node, javalang.tree.AnnotationDeclaration):
            kind = "class"
        else:
            kind = "class"

        line_start = node.position.line if node.position else 1
        line_end = calculate_block_end_line(source_lines, line_start)
        fqdn = build_fqdn(scope_stack, name)
        doc = clean_docstring(getattr(node, "documentation", ""))

        modifiers = list(getattr(node, "modifiers", []))
        mod_prefix = f"{' '.join(sorted(modifiers))} " if modifiers else ""
        if isinstance(node, javalang.tree.EnumDeclaration):
            signature = f"{mod_prefix}enum {name}".strip()
        elif isinstance(node, javalang.tree.InterfaceDeclaration):
            signature = f"{mod_prefix}interface {name}".strip()
        elif isinstance(node, javalang.tree.AnnotationDeclaration):
            signature = f"{mod_prefix}@interface {name}".strip()
        else:
            signature = f"{mod_prefix}class {name}".strip()

        child_scope = scope_stack + [name]
        children: List[Symbol] = []

        # 1. Enum Constants
        if isinstance(node, javalang.tree.EnumDeclaration) and hasattr(
            node, "body"
        ):
            if hasattr(node.body, "constants") and node.body.constants:
                for const in node.body.constants:
                    c_name = const.name
                    c_pos = (
                        const.position.line
                        if const.position
                        else line_start
                    )
                    c_fqdn = build_fqdn(child_scope, c_name)
                    c_doc = clean_docstring(
                        getattr(const, "documentation", "")
                    )
                    children.append(
                        Symbol(
                            name=c_name,
                            kind="enum_constant",
                            line_start=c_pos,
                            line_end=c_pos,
                            fqdn=c_fqdn,
                            signature=f"{c_name}",
                            doc=c_doc,
                        )
                    )

        # 2. Fields
        if hasattr(node, "fields"):
            for field in node.fields:
                f_type_str = _format_type(field.type)
                f_doc = clean_docstring(getattr(field, "documentation", ""))
                f_mods = list(getattr(field, "modifiers", []))
                f_mod_str = f"{' '.join(sorted(f_mods))} " if f_mods else ""

                for decl in field.declarators:
                    f_name = decl.name
                    if decl.position:
                        f_pos = decl.position.line
                    elif field.position:
                        f_pos = field.position.line
                    else:
                        f_pos = line_start
                    f_fqdn = build_fqdn(child_scope, f_name)
                    f_sig = f"{f_mod_str}{f_type_str} {f_name}".strip()
                    children.append(
                        Symbol(
                            name=f_name,
                            kind="field",
                            line_start=f_pos,
                            line_end=f_pos,
                            fqdn=f_fqdn,
                            signature=f_sig,
                            doc=f_doc,
                        )
                    )

        # 3. Constructors
        if hasattr(node, "constructors"):
            for constr in node.constructors:
                c_name = constr.name
                c_pos = constr.position.line if constr.position else line_start
                c_end = calculate_block_end_line(source_lines, c_pos)
                c_fqdn = build_fqdn(child_scope, c_name)
                c_doc = clean_docstring(getattr(constr, "documentation", ""))

                c_params: List[Parameter] = []
                for p in getattr(constr, "parameters", []):
                    c_params.append(
                        Parameter(
                            name=p.name,
                            type_hint=_format_type(p.type),
                        )
                    )

                c_callees = _extract_java_callees(constr)
                c_mods = list(getattr(constr, "modifiers", []))
                c_mod_str = f"{' '.join(sorted(c_mods))} " if c_mods else ""
                param_strs = [
                    f"{p.type_hint} {p.name}" if p.type_hint else p.name
                    for p in c_params
                ]
                c_sig = f"{c_mod_str}{c_name}({', '.join(param_strs)})"

                children.append(
                    Symbol(
                        name=c_name,
                        kind="constructor",
                        line_start=c_pos,
                        line_end=c_end,
                        fqdn=c_fqdn,
                        signature=c_sig.strip(),
                        doc=c_doc,
                        parameters=c_params,
                        return_type="",
                        callees=c_callees,
                    )
                )

        # 4. Methods
        if hasattr(node, "methods"):
            for method in node.methods:
                m_name = method.name
                m_pos = method.position.line if method.position else line_start
                m_end = calculate_block_end_line(source_lines, m_pos)
                m_fqdn = build_fqdn(child_scope, m_name)
                m_doc = clean_docstring(getattr(method, "documentation", ""))

                m_params: List[Parameter] = []
                for p in getattr(method, "parameters", []):
                    m_params.append(
                        Parameter(
                            name=p.name,
                            type_hint=_format_type(p.type),
                        )
                    )

                ret_type = _format_type(method.return_type)
                m_callees = _extract_java_callees(method)
                m_mods = list(getattr(method, "modifiers", []))
                m_mod_str = f"{' '.join(sorted(m_mods))} " if m_mods else ""
                param_strs = [
                    f"{p.type_hint} {p.name}" if p.type_hint else p.name
                    for p in m_params
                ]
                params_joined = ", ".join(param_strs)
                m_sig = f"{m_mod_str}{ret_type} {m_name}({params_joined})"

                children.append(
                    Symbol(
                        name=m_name,
                        kind="method",
                        line_start=m_pos,
                        line_end=m_end,
                        fqdn=m_fqdn,
                        signature=m_sig.strip(),
                        doc=m_doc,
                        parameters=m_params,
                        return_type=ret_type,
                        callees=m_callees,
                    )
                )

        # 5. Nested / Inner Types
        if hasattr(node, "body") and isinstance(node.body, list):
            for body_item in node.body:
                if isinstance(
                    body_item,
                    (
                        javalang.tree.ClassDeclaration,
                        javalang.tree.InterfaceDeclaration,
                        javalang.tree.EnumDeclaration,
                    ),
                ):
                    nested_sym = self._parse_type_declaration(
                        body_item, source_lines, child_scope
                    )
                    if nested_sym:
                        children.append(nested_sym)

        return Symbol(
            name=name,
            kind=kind,
            line_start=line_start,
            line_end=line_end,
            fqdn=fqdn,
            signature=signature,
            doc=doc,
            children=children,
        )
