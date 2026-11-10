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
    python tools/build_digit_bank.py rebuild --job <job_id> --dry-run
    python tools/build_digit_bank.py rebuild --job <job_id>
    python tools/build_digit_bank.py purge --job <job_id>

``rebuild`` replaces a job's samples with what the reader as it is now makes
of the pages a human graded -- for a job banked by a reader that has since
been fixed. ``purge`` only takes a job's samples out. Run either while no job
is being finalised: the index is rewritten whole.

``STORAGE`` and the ``MONGODB_*`` variables select the tree and the database,
exactly as they do for the executor itself.
"""

import argparse
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXECUTOR = os.path.dirname(HERE)
sys.path.insert(0, EXECUTOR)
sys.path.insert(0, os.path.join(EXECUTOR, "python"))
sys.path.insert(0, os.path.join(os.path.dirname(EXECUTOR), "common"))

from process_copy import auto_grade, digit_bank  # noqa: E402
from process_copy.database import Database  # noqa: E402
from rmn_common.status import Job_Status  # noqa: E402
from rmn_common.storage import Storage  # noqa: E402


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
                db, job_id, storage, remove=not args.keep_staged, final=args.final
            )
            for key, value in counts.items():
                # "refused" only appears for a job whose owner opted out
                totals[key] = totals.get(key, 0) + value
            print(job_id, ", ".join(f"{k}={v}" for k, v in counts.items()))
        print("total", ", ".join(f"{k}={v}" for k, v in totals.items()))
    finally:
        db.close()


def purge(args, storage) -> None:
    """Take a job's samples out of the bank."""
    counts = digit_bank.purge_job(storage, args.job, dry_run=args.dry_run)
    verb = "would remove" if args.dry_run else "removed"
    print(f"{args.job}: {verb} {counts['lines']} index lines, {counts['files']} files")


def rebuild(args, storage) -> None:
    """Re-read a job's graded pages and replace its samples with those readings.

    The new readings are staged before anything is removed, so a pass that
    fails half way leaves the bank as it was. A dry run stages and promotes
    into a throwaway tree and reports what the job would hold instead.
    """
    from process_copy.classifier import load_classifier

    db = Database()
    try:
        job = db.eval_jobs_collection().find_one({"job_id": args.job})
        if not job:
            print(f"{args.job}: no such job")
            return
        if not digit_bank.saves_images(db):
            print("The bank is switched off on the admin page: nothing to rebuild.")
            return
        questions = sorted(
            db.questions_collection().distinct("question_index", {"job_id": args.job})
        )
        classifier = load_classifier()
        with tempfile.TemporaryDirectory() as scratch:
            bank = Storage(scratch) if args.dry_run else storage
            pages = staged = 0
            for question in questions:
                counts = auto_grade.restage_question(
                    db, storage, job, question, classifier, bank_storage=bank
                )
                pages += counts["pages"]
                staged += counts["staged"]
                print(
                    f"  Q{question}: {counts['pages']} pages, {counts['staged']} kept"
                )
            removed = digit_bank.purge_job(storage, args.job, dry_run=args.dry_run)
            final = job.get("job_status") == Job_Status.ARCHIVED.value
            promoted = digit_bank.promote_job(db, args.job, bank, final=final)
            labels = digit_bank.counts(bank) if args.dry_run else None
        verb = "would replace" if args.dry_run else "replaced"
        print(
            f"{args.job}: {pages} pages read, {staged} readings kept; {verb} "
            f"{removed['lines']} samples by {promoted.get('samples', 0)}"
        )
        if labels is not None:
            print("  new samples per digit:", dict(sorted(labels.items())))
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
        "--keep-staged",
        action="store_true",
        help="do not delete the staged readings (to promote again later)",
    )
    p_promote.add_argument(
        "--final",
        action="store_true",
        help="the task is over: drop what could not be labelled, as finalising does",
    )

    p_purge = sub.add_parser("purge", help="take a job's samples out of the bank")
    p_purge.add_argument("--job", required=True)
    p_purge.add_argument("--dry-run", action="store_true", help="count only")

    p_rebuild = sub.add_parser(
        "rebuild", help="re-read a job's graded pages and replace its samples"
    )
    p_rebuild.add_argument("--job", required=True)
    p_rebuild.add_argument(
        "--dry-run",
        action="store_true",
        help="read into a throwaway tree and report, change nothing",
    )

    p_export = sub.add_parser("export", help="write the bank as a training set")
    p_export.add_argument(
        "--size",
        type=int,
        default=28,
        help="side of the exported images (default: the model's 28)",
    )
    p_export.add_argument(
        "--margin",
        type=float,
        default=0.1,
        help="margin around the digit, as a fraction of its size",
    )
    p_export.add_argument("--out", default="dataset_confirmed.npy")

    args = parser.parse_args(argv)
    storage = digit_bank.default_storage
    print("Storage:", storage.path)

    if args.command == "stats":
        print_stats(storage)
    elif args.command == "promote":
        promote(args, storage)
    elif args.command == "purge":
        purge(args, storage)
    elif args.command == "rebuild":
        rebuild(args, storage)
    elif args.command == "export":
        export(args, storage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
