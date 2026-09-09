import re
from dataclasses import dataclass, field
from typing import Any, List, Optional


def calculate_symbol_complexity(
    code: str,
    callees: Optional[List[str]] = None,
    params: Optional[List[Any]] = None,
) -> float:
    """Estimate cyclomatic and structural complexity of a symbol."""
    if not code:
        return 1.0
    branch_keywords = (
        r"\b(if|elif|else|for|while|switch|case|catch|except|try|match|when|"
        r"guard|yield|async|await|return|break|continue)\b|\&\&|\|\||\?|=>"
    )
    branch_count = len(re.findall(branch_keywords, code))
    callee_count = len(callees or [])
    param_count = len(params or [])
    line_count = len(code.splitlines())
    return max(
        1.0,
        1.0
        + branch_count * 0.5
        + callee_count * 0.3
        + param_count * 0.2
        + line_count * 0.05,
    )


def get_kind_prefix(kind: str) -> str:
    """Return category prefix for file naming: fn, var, type, const."""
    kind_lower = kind.lower()
    if kind_lower in (
        "function",
        "async_function",
        "method",
        "constructor",
        "destructor",
    ):
        return "fn"
    elif kind_lower in ("variable", "var"):
        return "var"
    elif kind_lower in (
        "struct",
        "class",
        "enum",
        "interface",
        "annotation",
        "object",
        "typedef",
        "type_alias",
        "type",
        "field",
        "member",
        "property",
    ):
        return "type"
    elif kind_lower in ("enum_constant", "constant", "macro", "const"):
        return "const"
    return "sym"


@dataclass
class Parameter:
    name: str
    type_hint: str = ""
    default_value: str = ""
    description: str = ""


@dataclass
class Symbol:
    name: str
    kind: str  # function, method, class, struct, enum, variable, field, etc.
    line_start: int
    line_end: int
    # Fully Qualified Domain Name (e.g. src.network.client.fetch_data)
    fqdn: str = ""
    signature: str = ""
    doc: str = ""
    purpose: str = ""
    parameters: List[Parameter] = field(default_factory=list)
    return_type: str = ""
    return_doc: str = ""
    inputs_note: str = ""
    outputs_note: str = ""
    global_reads: List[str] = field(default_factory=list)
    global_writes: List[str] = field(default_factory=list)
    callees: List[str] = field(default_factory=list)
    referencing_functions: List[str] = field(default_factory=list)
    overview: str = ""
    top_down_context: str = ""
    complexity: float = 1.0
    logic_hash: str = ""
    full_hash: str = ""
    ast_node: Optional[Any] = None
    children: List["Symbol"] = field(default_factory=list)

    @property
    def kind_prefix(self) -> str:
        return get_kind_prefix(self.kind)
