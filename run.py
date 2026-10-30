#!/usr/bin/env python3
"""不加参数也能跑的入口。

    python run.py                    # 等价于 `python -m typesmith`
    python run.py specimen --out docs/01-specimen.png
    python run.py serve
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typesmith.cli import main

if __name__ == "__main__":
    sys.exit(main())
