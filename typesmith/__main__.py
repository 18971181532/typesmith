"""让 `python -m typesmith` 直接可用。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
