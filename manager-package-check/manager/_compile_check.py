"""Compile-check all manager Python source files."""
import py_compile, sys, pathlib

base = pathlib.Path(__file__).parent
targets = [
    "app/__init__.py",
    "app/config.py",
    "app/auth.py",
    "app/middleware.py",
    "app/schemas.py",
    "app/routes.py",
    "app/main.py",
    "run.py",
    "__init__.py",
    "tests/__init__.py",
    "tests/test_manager.py",
]

failures = []
for rel in targets:
    p = base / rel
    try:
        py_compile.compile(str(p), doraise=True)
        print(f"OK   {rel}")
    except py_compile.PyCompileError as e:
        print(f"FAIL {rel}: {e}")
        failures.append(rel)

if failures:
    print(f"\n{len(failures)} file(s) failed compilation.")
    sys.exit(1)
else:
    print(f"\nAll {len(targets)} files compiled successfully.")
