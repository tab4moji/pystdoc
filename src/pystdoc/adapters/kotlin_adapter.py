"""Kotlin language adapter using kopyt AST parser."""

from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

import kopyt
import kopyt.node

from pystdoc.adapters.base import (
    BaseLanguageAdapter,
    build_fqdn,
    calculate_block_end_line,
    clean_docstring,
)
from pystdoc.compilation_db import CompilationDatabase
from pystdoc.symbols import Parameter, Symbol


def _format_type_node(type_node: Any) -> str:
    """Format kopyt type node into a clean string representation."""
    if type_node is None:
        return ""
    if isinstance(type_node, str):
        return type_node
    sub = getattr(type_node, "subtype", type_node)
    if isinstance(sub, kopyt.node.TypeReference):
        sub = sub.subtype
    if isinstance(sub, kopyt.node.UserType):
        parts = []
        for s in getattr(sub, "sequence", []):
            name = getattr(s, "name", "")
            if hasattr(s, "generics") and s.generics:
                gen_parts = [
                    _format_type_node(
                        getattr(g, "type", g)
                    ) for g in s.generics
                ]
                parts.append(f"{name}<{', '.join(gen_parts)}>")
            else:
                parts.append(str(name))
        return ".".join(parts)
    elif isinstance(sub, kopyt.node.NullableType):
        inner = _format_type_node(
            getattr(sub, "subtype", getattr(sub, "type", None))
        )
        return f"{inner}?" if inner else "Any?"
    elif hasattr(sub, "name"):
        return str(sub.name)
    return str(type_node)


def _extract_preceding_doc(source_lines: List[str], start_line: int) -> str:
    """Extract preceding KDoc or comment lines before start_line."""
    if start_line <= 1 or start_line > len(source_lines):
        return ""
    idx = start_line - 2
    comment_lines = []

    # Skip preceding annotations (e.g. @Service, @Override)
    while idx >= 0 and source_lines[idx].strip().startswith("@"):
        idx -= 1

    if idx >= 0 and source_lines[idx].strip().endswith("*/"):
        while idx >= 0:
            line = source_lines[idx].strip()
            comment_lines.insert(0, line)
            if line.startswith("/*"):
                break
            idx -= 1
        return clean_docstring("\n".join(comment_lines))
    elif idx >= 0 and source_lines[idx].strip().startswith("//"):
        while idx >= 0 and source_lines[idx].strip().startswith("//"):
            comment_lines.insert(0, source_lines[idx].strip())
            idx -= 1
        return clean_docstring("\n".join(comment_lines))
    return ""


def _extract_kotlin_callees(node: Any) -> List[str]:
    """Extract function and method calls from Kotlin AST nodes."""
    callees: Set[str] = set()

    def walk(n):
        if n is None:
            return
        if isinstance(n, (list, tuple, set)):
            for item in n:
                walk(item)
            return
        if isinstance(n, kopyt.node.Node):
            if isinstance(n, kopyt.node.PostfixUnaryExpression):
                has_call = any(
                    isinstance(s, kopyt.node.CallSuffix)
                    for s in (n.suffixes or [])
                )
                if has_call:
                    nav_suffixes = [
                        s
                        for s in (n.suffixes or [])
                        if isinstance(s, kopyt.node.NavigationSuffix)
                    ]
                    if nav_suffixes:
                        callees.add(nav_suffixes[-1].suffix)
                    elif isinstance(n.expression, kopyt.node.SimpleIdentifier):
                        callees.add(n.expression.value)
            for slot in getattr(n, "__slots__", []):
                val = getattr(n, slot, None)
                walk(val)

    walk(node)
    return sorted(list(callees))


class KotlinAdapter(BaseLanguageAdapter):
    """Adapter for Kotlin source files using kopyt AST."""

    @property
    def name(self) -> str:
        return "kotlin"

    @property
    def supported_extensions(self) -> Tuple[str, ...]:
        return (".kt", ".kts")

    @property
    def default_code_language(self) -> str:
        return "kotlin"

    def parse(
        self,
        file_path: Path,
        comp_db: Optional[CompilationDatabase] = None,
        base_dir: Optional[Path] = None,
    ) -> List[Symbol]:
        """Parse Kotlin file and return hierarchical Symbol list."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            source_lines = content.splitlines()
            parser = kopyt.Parser(content)
            tree = parser.parse()
        except Exception:
            return []

        package_name = ""
        if getattr(tree, "package", None):
            pkg_obj = tree.package
            if hasattr(pkg_obj, "name") and pkg_obj.name:
                package_name = str(pkg_obj.name).strip()
            elif hasattr(pkg_obj, "sequence") and pkg_obj.sequence:
                package_parts = []
                for s in pkg_obj.sequence:
                    val = getattr(s, "value", getattr(s, "name", str(s)))
                    package_parts.append(str(val))
                package_name = ".".join(package_parts)
            elif hasattr(pkg_obj, "header"):
                header_str = str(pkg_obj.header).strip()
                if header_str.startswith("package"):
                    header_str = header_str[7:].strip()
                package_parts = [
                    p.strip()
                    for p in header_str.split(".")
                    if p.strip()
                ]
                package_name = ".".join(package_parts)

        file_prefix = file_path.stem
        scope_prefix = package_name if package_name else file_prefix

        symbols: List[Symbol] = []
        for decl in getattr(tree, "declarations", []):
            parsed_sym = self._parse_declaration(
                decl, source_lines, [scope_prefix]
            )
            if parsed_sym:
                if isinstance(parsed_sym, list):
                    symbols.extend(parsed_sym)
                else:
                    symbols.append(parsed_sym)

        return symbols

    def _parse_declaration(
        self,
        decl: Any,
        source_lines: List[str],
        scope_stack: List[str],
    ) -> Any:
        """Parse any top-level or member declaration in Kotlin AST."""
        if decl is None:
            return None

        # 1. Class / Interface / Object / Enum Class
        if isinstance(
            decl,
            (
                kopyt.node.ClassDeclaration,
                kopyt.node.InterfaceDeclaration,
                kopyt.node.EnumDeclaration,
                kopyt.node.ObjectDeclaration,
                kopyt.node.CompanionObject,
            ),
        ):
            return self._parse_class_like(decl, source_lines, scope_stack)

        # 2. Function
        elif isinstance(decl, kopyt.node.FunctionDeclaration):
            return self._parse_function(decl, source_lines, scope_stack)

        # 3. Property (val / var)
        elif isinstance(decl, kopyt.node.PropertyDeclaration):
            return self._parse_property(decl, source_lines, scope_stack)

        # 4. Secondary Constructor
        elif isinstance(decl, kopyt.node.SecondaryConstructor):
            return self._parse_secondary_constructor(
                decl, source_lines, scope_stack
            )

        return None

    def _parse_class_like(
        self,
        node: Any,
        source_lines: List[str],
        scope_stack: List[str],
    ) -> Optional[Symbol]:
        raw_name = getattr(node, "name", None)
        raw_name_str = str(raw_name) if raw_name else ""

        modifiers = list(getattr(node, "modifiers", []))

        # Handle Kotlin companion objects (with default or keyword-like names)
        if isinstance(node, kopyt.node.CompanionObject):
            kind = "class"
            if not raw_name_str or raw_name_str in (
                "public",
                "private",
                "internal",
                "protected",
            ):
                if raw_name_str and raw_name_str not in modifiers:
                    modifiers.append(raw_name_str)
                name = "Companion"
            else:
                name = raw_name_str
        elif isinstance(node, kopyt.node.EnumDeclaration):
            kind = "enum"
            name = raw_name_str if raw_name_str else "Anonymous"
        elif isinstance(node, kopyt.node.InterfaceDeclaration):
            kind = "class"
            name = raw_name_str if raw_name_str else "Anonymous"
        elif isinstance(node, kopyt.node.ObjectDeclaration):
            kind = "class"
            name = raw_name_str if raw_name_str else "Anonymous"
        else:
            kind = "class"
            name = raw_name_str if raw_name_str else "Anonymous"

        pos = getattr(node, "position", None)
        line_start = pos.line if pos else 1
        line_end = calculate_block_end_line(source_lines, line_start)
        fqdn = build_fqdn(scope_stack, name)
        doc = _extract_preceding_doc(source_lines, line_start)

        mod_parts = [str(m) for m in modifiers]
        mod_prefix = f"{' '.join(mod_parts)} " if mod_parts else ""

        if isinstance(node, kopyt.node.CompanionObject):
            if name == "Companion":
                signature = f"{mod_prefix}companion object".strip()
            else:
                signature = f"{mod_prefix}companion object {name}".strip()
        elif isinstance(node, kopyt.node.EnumDeclaration):
            signature = f"{mod_prefix}enum class {name}".strip()
        elif isinstance(node, kopyt.node.InterfaceDeclaration):
            signature = f"{mod_prefix}interface {name}".strip()
        elif isinstance(node, kopyt.node.ObjectDeclaration):
            signature = f"{mod_prefix}object {name}".strip()
        else:
            signature = f"{mod_prefix}class {name}".strip()

        child_scope = scope_stack + [name]
        children: List[Symbol] = []

        # Extract primary constructor parameters if properties (val / var)
        if hasattr(node, "constructor") and node.constructor:
            ctor = node.constructor
            if hasattr(ctor, "parameters") and ctor.parameters:
                params_seq = getattr(ctor.parameters, "sequence", [])
                for p in params_seq:
                    p_name = getattr(p, "name", "")
                    p_type = _format_type_node(getattr(p, "type", None))
                    p_pos = getattr(p, "position", None)
                    p_line = p_pos.line if p_pos else line_start
                    p_fqdn = build_fqdn(child_scope, p_name)
                    p_mut = getattr(p, "mutability", None)
                    p_mut_str = f"{p_mut.value} " if p_mut else ""
                    if p_name and (p_mut or getattr(p, "modifiers", None)):
                        p_sig = f"{p_mut_str}{p_name}: {p_type}".strip()
                        children.append(
                            Symbol(
                                name=p_name,
                                kind="field",
                                line_start=p_line,
                                line_end=p_line,
                                fqdn=p_fqdn,
                                signature=p_sig,
                                doc="",
                            )
                        )

        # Extract enum entries
        if isinstance(node, kopyt.node.EnumDeclaration):
            body = getattr(node, "body", None)
            if body and hasattr(body, "entries") and body.entries:
                for entry in body.entries:
                    e_name = getattr(entry, "name", "")
                    e_pos = getattr(entry, "position", None)
                    e_line = e_pos.line if e_pos else line_start
                    e_fqdn = build_fqdn(child_scope, e_name)
                    e_doc = _extract_preceding_doc(source_lines, e_line)
                    children.append(
                        Symbol(
                            name=e_name,
                            kind="enum_constant",
                            line_start=e_line,
                            line_end=e_line,
                            fqdn=e_fqdn,
                            signature=e_name,
                            doc=e_doc,
                        )
                    )

        # Extract members from class body
        body = getattr(node, "body", None)
        if body and hasattr(body, "members") and body.members:
            for member in body.members:
                parsed_child = self._parse_declaration(
                    member, source_lines, child_scope
                )
                if parsed_child:
                    if isinstance(parsed_child, list):
                        children.extend(parsed_child)
                    else:
                        children.append(parsed_child)

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

    def _parse_function(
        self,
        node: Any,
        source_lines: List[str],
        scope_stack: List[str],
    ) -> Symbol:
        name = getattr(node, "name", "anonymousFunction")
        pos = getattr(node, "position", None)
        line_start = pos.line if pos else 1
        line_end = calculate_block_end_line(source_lines, line_start)
        fqdn = build_fqdn(scope_stack, name)
        doc = _extract_preceding_doc(source_lines, line_start)

        params: List[Parameter] = []
        if hasattr(node, "parameters") and node.parameters:
            for p_item in getattr(node.parameters, "sequence", []):
                inner_p = getattr(p_item, "parameter", p_item)
                p_name = getattr(inner_p, "name", "")
                p_type = _format_type_node(getattr(inner_p, "type", None))
                if p_name:
                    params.append(Parameter(name=p_name, type_hint=p_type))

        ret_type = _format_type_node(getattr(node, "type", None))
        callees = _extract_kotlin_callees(getattr(node, "body", None))

        modifiers = list(getattr(node, "modifiers", []))
        mod_parts = [str(m) for m in modifiers]
        mod_prefix = f"{' '.join(mod_parts)} " if mod_parts else ""
        param_strs = [
            f"{p.name}: {p.type_hint}" if p.type_hint else p.name
            for p in params
        ]
        ret_suffix = f": {ret_type}" if ret_type else ""
        param_joined = ", ".join(param_strs)
        signature = (
            f"{mod_prefix}fun {name}({param_joined}){ret_suffix}".strip()
        )

        kind = "method" if len(scope_stack) > 1 else "function"

        return Symbol(
            name=name,
            kind=kind,
            line_start=line_start,
            line_end=line_end,
            fqdn=fqdn,
            signature=signature,
            doc=doc,
            parameters=params,
            return_type=ret_type,
            callees=callees,
        )

    def _parse_property(
        self,
        node: Any,
        source_lines: List[str],
        scope_stack: List[str],
    ) -> Optional[Symbol]:
        decl = getattr(node, "declaration", None)
        if not decl:
            return None
        name = getattr(decl, "name", "")
        if not name:
            return None

        pos = getattr(node, "position", getattr(decl, "position", None))
        line_start = pos.line if pos else 1
        line_end = calculate_block_end_line(source_lines, line_start)
        fqdn = build_fqdn(scope_stack, name)
        doc = _extract_preceding_doc(source_lines, line_start)

        prop_type = _format_type_node(getattr(decl, "type", None))
        mut = getattr(node, "mutability", None)
        mut_str = f"{mut.value} " if mut else "val "
        modifiers = list(getattr(node, "modifiers", []))
        mod_parts = [str(m) for m in modifiers]
        mod_prefix = f"{' '.join(mod_parts)} " if mod_parts else ""

        type_str = f": {prop_type}" if prop_type else ""
        signature = f"{mod_prefix}{mut_str}{name}{type_str}".strip()

        kind = "field" if len(scope_stack) > 1 else "variable"

        return Symbol(
            name=name,
            kind=kind,
            line_start=line_start,
            line_end=line_end,
            fqdn=fqdn,
            signature=signature,
            doc=doc,
        )

    def _parse_secondary_constructor(
        self,
        node: Any,
        source_lines: List[str],
        scope_stack: List[str],
    ) -> Symbol:
        name = scope_stack[-1] if scope_stack else "constructor"
        pos = getattr(node, "position", None)
        line_start = pos.line if pos else 1
        line_end = calculate_block_end_line(source_lines, line_start)
        fqdn = build_fqdn(scope_stack, "constructor")
        doc = _extract_preceding_doc(source_lines, line_start)

        params: List[Parameter] = []
        if hasattr(node, "parameters") and node.parameters:
            for p_item in getattr(node.parameters, "sequence", []):
                inner_p = getattr(p_item, "parameter", p_item)
                p_name = getattr(inner_p, "name", "")
                p_type = _format_type_node(getattr(inner_p, "type", None))
                if p_name:
                    params.append(Parameter(name=p_name, type_hint=p_type))

        callees = _extract_kotlin_callees(getattr(node, "body", None))
        param_strs = [
            f"{p.name}: {p.type_hint}" if p.type_hint else p.name
            for p in params
        ]
        signature = f"constructor({', '.join(param_strs)})"

        return Symbol(
            name=name,
            kind="constructor",
            line_start=line_start,
            line_end=line_end,
            fqdn=fqdn,
            signature=signature,
            doc=doc,
            parameters=params,
            return_type="",
            callees=callees,
        )
