# -*- coding: utf-8 -*-
"""Crude undefined-name / unused-import check (no external linter needed)."""
import ast, builtins, sys

def check(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    defined, loads, imported = set(dir(builtins)), [], {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                nm = (a.asname or a.name).split(".")[0]
                defined.add(nm); imported[nm] = n.lineno
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            defined.add(n.name)
            if not isinstance(n, ast.ClassDef):
                for a in n.args.args + n.args.kwonlyargs + n.args.posonlyargs:
                    defined.add(a.arg)
                if n.args.vararg: defined.add(n.args.vararg.arg)
                if n.args.kwarg: defined.add(n.args.kwarg.arg)
        elif isinstance(n, ast.Lambda):
            for a in n.args.args: defined.add(a.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
        elif isinstance(n, ast.Name):
            (defined.add(n.id) if isinstance(n.ctx, (ast.Store, ast.Del)) else loads.append((n.id, n.lineno)))
    used = {n for n, _ in loads} | {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    src = open(path, encoding="utf-8").read()
    problems = [f"{path}:{l}: undefined name {n}" for n, l in loads if n not in defined]
    problems += [f"{path}:{l}: unused import {n}" for n, l in imported.items() if n not in used and n not in src.replace("import","",1).split("__all__")[-1:][0][:0] and src.count(n) < 2]
    return problems

if __name__ == "__main__":
    bad = [p for f in sys.argv[1:] for p in check(f)]
    print("\n".join(bad) or "OK: no undefined names")
    sys.exit(1 if bad else 0)
