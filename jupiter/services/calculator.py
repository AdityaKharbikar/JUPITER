from ..common import *


class CalculatorService:
    def _safe_eval_math(self, expr: str):
        node = ast.parse(expr, mode="eval").body

        def _eval(n):
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
                return n.value
            if isinstance(n, ast.BinOp) and type(n.op) in self._SAFE_MATH_OPERATORS:
                if isinstance(n.op, ast.Pow):
                    base, exp = _eval(n.left), _eval(n.right)
                    if abs(exp) > 1000 or abs(base) > 1e12:
                        raise ValueError("Exponent too large")
                    return base ** exp
                return self._SAFE_MATH_OPERATORS[type(n.op)](_eval(n.left), _eval(n.right))
            if isinstance(n, ast.UnaryOp) and type(n.op) in self._SAFE_MATH_OPERATORS:
                return self._SAFE_MATH_OPERATORS[type(n.op)](_eval(n.operand))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in self._SAFE_MATH_FUNCS:
                if n.func.id == "pow":
                    raise ValueError("Use ** instead")
                return self._SAFE_MATH_FUNCS[n.func.id](*[_eval(a) for a in n.args])
            raise ValueError("Disallowed expression")

        return _eval(node)
