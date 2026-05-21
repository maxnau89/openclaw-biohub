"""Allow `python -m biohub ...` to work the same as the `biohub` script."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
