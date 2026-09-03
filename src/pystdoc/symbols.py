"""Symbol and Parameter data structures for unified documentation."""

from dataclasses import dataclass, field
from typing import List


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
        "typedef",
        "type_alias",
        "type",
        "field",
        "member",
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
    children: List["Symbol"] = field(default_factory=list)

    @property
    def kind_prefix(self) -> str:
        return get_kind_prefix(self.kind)
