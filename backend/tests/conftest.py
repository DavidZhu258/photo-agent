from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path


TEST_DEPS = Path(__file__).resolve().parents[1] / ".test_deps"
if TEST_DEPS.exists():
    sys.path.insert(0, str(TEST_DEPS))


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: run async test functions with asyncio.run")


def pytest_pyfunc_call(pyfuncitem):
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
        if name in pyfuncitem.funcargs
    }
    asyncio.run(pyfuncitem.obj(**kwargs))
    return True
