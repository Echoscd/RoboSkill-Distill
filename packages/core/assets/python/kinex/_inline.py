"""Execute an inline lambda or a module defining main."""

import ast
from kinex import _request, args, finish


def run(source, values):
    tree = ast.parse(source, filename="<inline>")
    namespace = {"__name__": "__kinex_inline__"}
    if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Lambda):
        function = eval(compile(ast.Expression(tree.body[0].value), "<inline>", "eval"), namespace)
    else:
        exec(compile(tree, "<inline>", "exec"), namespace)
        function = namespace.get("main")
    if not callable(function):
        raise ValueError("inline Python must be a lambda or define main")
    return function(**values)


if __name__ == "__main__":
    if _request is None or not isinstance(_request.get("source"), str):
        raise ValueError("inline startup request requires source")
    finish(run(_request["source"], args()))
