import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from registry.generate import check_registry, generate_registry, registry_diff


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        if check_registry(args.source, args.output):
            return 0
        print(f"registry artifact is stale or missing: {args.output}", file=sys.stderr)
        print(registry_diff(args.source, args.output), file=sys.stderr, end="")
        return 1
    generate_registry(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
