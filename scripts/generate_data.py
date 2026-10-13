"""Write the lubricants dataset to data/ (`make data`). Same seed, same files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ddmrp_buffers import config, data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--seed", type=int, default=config.SEED)
    args = parser.parse_args()
    ds = data.generate(seed=args.seed)
    data.save(ds, args.out)
    print(json.dumps(data.summary(ds), indent=2))


if __name__ == "__main__":
    main()
