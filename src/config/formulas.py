import ast
import math
from typing import Sequence, Dict

from .schemas import MetricsConfig
from .exceptions import InvalidSchemaError

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
    ast.keyword,
)

ALLOWED_FUNCTIONS = {
    "abs": abs,
    "min": min,
    "max": max,
    "clamp": lambda val, low, high: max(low, min(val, high)),
    "sqrt": math.sqrt,
    "log": math.log,
    "exp": math.exp,
    "pow": pow
}

# ====================================
# RUNTIME EVALUATOR
# ====================================

class SafeFormulaEvaluator(ast.NodeVisitor):
    """
    Evaluate sanitized AST expressions
    """
    ALLOWED_FUNCTIONS = ALLOWED_FUNCTIONS

    def __init__(self, variables: Dict[str, float]):
        self.variables = variables

    def evaluate(self, expression: str) -> float:
        parsed_ast = ast.parse(expression, mode="eval")
        return float(self.visit(parsed_ast.body))

    def visit_Constant(self, node: ast.Constant) -> float:
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsupported constant type: {type(node.value)}")

    def visit_Name(self, node: ast.Name) -> float:
        if node.id in self.variables:
            return float(self.variables[node.id])
        raise ValueError(f"Undeclared metric variable in AST evaluation: '{node.id}'")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> float:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise ValueError(f"Unsupported unary operator: {type(node.op)}")

    def visit_BinOp(self, node: ast.BinOp) -> float:
        left = self.visit(node.left)
        right = self.visit(node.right)

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0.0:
                raise ZeroDivisionError(f"Division by zero in formula evaluation: {left} / {right}")
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0.0:
                raise ZeroDivisionError(f"Floor division by zero in formula evaluation: {left} // {right}")
            return float(left//right)
        if isinstance(node.op, ast.Pow):
            return left ** right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise ValueError(f"Unsupported binary operator: {type(node.op)}")

    def visit_Call(self, node: ast.Call) -> float:
        if not isinstance(node.func, ast.Name) or node.func.id not in self.ALLOWED_FUNCTIONS:
            func_name = node.func.id if isinstance(node.func, ast.Name) else "complex expression"
            raise ValueError(f"Disallowed or unknown function call in AST: '{func_name}'")

        args = [self.visit(arg) for arg in node.args]
        kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords if kw.arg is not None}
        
        func = self.ALLOWED_FUNCTIONS[node.func.id]
        return float(func(*args, **kwargs))

    def generic_visit(self, node: ast.AST):
        raise ValueError(f"Disallowed AST expression syntax: {type(node).__name__}")

def evaluate_formula(expression: str, variables: Dict[str, float]) -> float:
    evaluator = SafeFormulaEvaluator(variables)
    return evaluator.evaluate(expression)

# ====================================
# RUNTIME EVALUATOR
# ====================================
class _ASTFormulaValidator(ast.NodeVisitor):
    ALLOWED_NODES = ALLOWED_NODES
    ALLOWED_FUNCTIONS = ALLOWED_FUNCTIONS

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
                f"Disallowed function call '{func_name}' in formula. Allowed functions: {sorted(self.ALLOWED_FUNCTIONS.keys())}."
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