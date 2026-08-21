import ast
from typing import Sequence

from .schemas import MetricsConfig
from .exceptions import InvalidSchemaError

class _ASTFormulaValidator(ast.NodeVisitor):
    ALLOWED_NODES = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Name,
        ast.Call,
        ast.Load,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.FloorDiv,
        ast.USub,
        ast.UAdd,
    )
    ALLOWED_FUNCTIONS = {"abs", "min", "max", "clamp", "sqrt", "log", "exp", "pow"}

    def __init__(self) -> None:
        self.variables: set[str] = set()

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, self.ALLOWED_NODES):
            raise InvalidSchemaError(
                f"Disallowed expression node '{type(node).__name__}' in formula."
            )
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self.variables.add(node.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name) or node.func.id not in self.ALLOWED_FUNCTIONS:
            func_name = node.func.id if isinstance(node.func, ast.Name) else "complex expression"
            raise InvalidSchemaError(
                f"Disallowed function call '{func_name}' in formula. Allowed functions: {sorted(self.ALLOWED_FUNCTIONS)}."
            )
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            self.visit(kw.value)

def validate_derivative_metric_formulas(metrics: Sequence[MetricsConfig]) -> None:
    """
    Validates formula AST syntax, variable resolution, and dependency graph acyclicity.
    """
    all_metric_names = {m.name for m in metrics}
    derivative_metrics = {m.name: m for m in metrics if m.is_derivative}
    deps: dict[str, set[str]] = {}

    for d_name, d_metric in derivative_metrics.items():
        if not d_metric.formula:
            raise InvalidSchemaError(
                f"Derivative metric '{d_name}' is missing an AST expression formula."
            )
        try:
            tree = ast.parse(d_metric.formula, mode="eval")
        except SyntaxError as e:
            raise InvalidSchemaError(
                f"Syntax error in formula for derivative metric '{d_name}': {e}"
            ) from e

        validator = _ASTFormulaValidator()
        validator.visit(tree)

        used_vars = {v for v in validator.variables if v not in _ASTFormulaValidator.ALLOWED_FUNCTIONS}
        for var in used_vars:
            if var not in all_metric_names:
                raise InvalidSchemaError(
                    f"Formula for derivative metric '{d_name}' references unknown metric variable '{var}'."
                )

        deps[d_name] = used_vars

    visited: set[str] = set()
    rec_stack: set[str] = set()

    def _dfs_cycle_check(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in deps.get(node, set()):
            if neighbor in derivative_metrics:
                if neighbor not in visited:
                    _dfs_cycle_check(neighbor, path)
                elif neighbor in rec_stack:
                    cycle = " -> ".join(path[path.index(neighbor):] + [neighbor])
                    raise InvalidSchemaError(
                        f"Circular dependency detected among derivative metrics: {cycle}"
                    )

        rec_stack.remove(node)
        path.pop()

    for d_metric_name in derivative_metrics:
        if d_metric_name not in visited:
            _dfs_cycle_check(d_metric_name, [])