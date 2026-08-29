"""docgen package: Code document generator using libclang, AST, and hierarchical architecture synthesis."""

from pystdoc.engine import run_docgen
from pystdoc.design_engine import run_design_generation
from pystdoc.report_engine import generate_readme_doc

__version__ = "0.1.0"
__all__ = ["run_docgen", "run_design_generation", "generate_readme_doc"]
