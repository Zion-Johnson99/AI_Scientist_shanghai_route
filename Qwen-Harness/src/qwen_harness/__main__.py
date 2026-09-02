"""支持 ``python -m qwen_harness`` 的入口（等价于 ``qwen-harness``）。"""

import sys

from qwen_harness.cli import main

if __name__ == "__main__":
    sys.exit(main())
