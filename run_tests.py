#!/usr/bin/env python3
"""跑全部单元测试。

    python run_tests.py              # 全部
    python run_tests.py -v           # 详细
    python run_tests.py layout       # 只跑名字里带 layout 的
"""

from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv) -> int:
    try:
        from typesmith.console import c, force_utf8, rule
        force_utf8()
    except Exception:                                   # pragma: no cover
        def c(text, *a):
            return text

        def rule(n=68, ch="-"):
            return ch * n

    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(os.path.dirname(__file__), "tests"),
                            top_level_dir=os.path.dirname(os.path.abspath(__file__)))
    pattern = next((a for a in argv if not a.startswith("-")), None)
    if pattern:
        suite = loader.discover(os.path.join(os.path.dirname(__file__), "tests"),
                                pattern=f"test_{pattern}*.py",
                                top_level_dir=os.path.dirname(os.path.abspath(__file__)))

    verbosity = 2 if any(a in ("-v", "--verbose") for a in argv) else 1
    print(c("TypeSmith", "bold") + c("  单元测试", "grey"))
    print(rule())
    t0 = time.time()
    result = unittest.TextTestRunner(verbosity=verbosity, buffer=True).run(suite)
    elapsed = time.time() - t0

    print(rule())
    total = result.testsRun
    skipped = len(result.skipped)
    print(f"共 {total} 个用例，跳过 {skipped}，"
          f"失败 {len(result.failures)}，错误 {len(result.errors)}，"
          f"用时 {elapsed:.2f}s")
    if result.wasSuccessful():
        print(c("全部通过", "green", "bold"))
        return 0
    print(c("有失败用例", "red", "bold"))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
