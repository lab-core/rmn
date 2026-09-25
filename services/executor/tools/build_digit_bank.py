"""Build and inspect the bank of human-confirmed digits.

The executor stages the crops of every number it reads and promotes them when
a job is finalised (``tasks.finalize``). This tool does the same work by hand,
for the jobs that were validated but never finalised, and turns the bank into
the arrays ``process_copy.train`` loads.

Usage:
    python tools/build_digit_bank.py stats
    python tools/build_digit_bank.py promote --job <job_id>
    python tools/build_digit_bank.py promote --all
    python tools/build_digit_bank.py export --size 28 --margin 0.1 \\
        --out dataset_confirmed.npy

``STORAGE`` and the ``MONGODB_*`` variables select the tree and the database,
exactly as they do for the executor itself.
"""

import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXECUTOR = os.path.dirname(HERE)
sys.path.insert(0, EXECUTOR)
sys.path.insert(0, os.path.join(EXECUTOR, "python"))
sys.path.insert(0, os.path.join(os.path.dirname(EXECUTOR), "common"))

from process_copy import digit_bank  # noqa: E402
from process_copy.database import Database  # noqa: E402


def print_stats(storage) -> None:
    """How many samples the bank holds, per digit."""
    counts = digit_bank.counts(storage)
    if not counts:
        print("The bank is empty.")
        return
    total = sum(counts.values())
    for digit in range(10):
        n = counts.get(digit, 0)
        bar = "#" * int(40 * n / max(counts.values()))
        print(f"  {digit}  {n:6d}  {bar}")
    print(f"  total {total}")


def promote(args, storage) -> None:
    """Promote one job, or every job that has staged readings."""
    db = Database()
    try:
        if args.job:
            job_ids = [args.job]
        else:
            root = storage.abs_path(digit_bank.STAGED_DIR)
            job_ids = sorted(os.listdir(root)) if os.path.isdir(root) else []
        if not job_ids:
            print("Nothing staged.")
            return
        totals = {"readings": 0, "promoted": 0, "samples": 0, "skipped": 0}
        for job_id in job_ids:
            counts = digit_bank.promote_job(
                db, job_id, storage, remove=not args.keep_staged
            )
            for key, value in counts.items():
                totals[key] += value
            print(job_id, ", ".join(f"{k}={v}" for k, v in counts.items()))
        print("total", ", ".join(f"{k}={v}" for k, v in totals.items()))
    finally:
        db.close()


def export(args, storage) -> None:
    """Write the bank as the ``(x, y)`` pair ``train.load_dataset`` reads."""
    x, y = digit_bank.samples(storage, size=args.size, margin=args.margin)
    if not len(x):
        print("The bank is empty: nothing exported.")
        return
    with open(args.out, "wb") as f:
        np.save(f, x)
        np.save(f, y)
    print(f"{len(x)} samples of {args.size}x{args.size} written to {args.out}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="how many samples the bank holds, per digit")

    p_promote = sub.add_parser("promote", help="label the staged readings of a job")
    group = p_promote.add_mutually_exclusive_group(required=True)
    group.add_argument("--job", help="the job to promote")
    group.add_argument("--all", action="store_true", help="every job with staged crops")
    p_promote.add_argument(
        "--keep-staged", action="store_true",
        help="do not delete the staged readings (to promote again later)")

    p_export = sub.add_parser("export", help="write the bank as a training set")
    p_export.add_argument("--size", type=int, default=28,
                          help="side of the exported images (default: the model's 28)")
    p_export.add_argument("--margin", type=float, default=0.1,
                          help="margin around the digit, as a fraction of its size")
    p_export.add_argument("--out", default="dataset_confirmed.npy")

    args = parser.parse_args(argv)
    storage = digit_bank.default_storage
    print("Storage:", storage.path)

    if args.command == "stats":
        print_stats(storage)
    elif args.command == "promote":
        promote(args, storage)
    elif args.command == "export":
        export(args, storage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
