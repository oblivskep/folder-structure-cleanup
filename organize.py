#!/usr/bin/env python3
import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class MovePlan:
    src: Path
    dst: Path


def slugify(name: str) -> str:
    name = name.strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9._-]+", "", name)
    name = re.sub(r"_+", "_", name)
    return name or "file"


def load_rules(rules_path: Path) -> dict:
    with rules_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extension_bucket(ext: str, rules: dict) -> str:
    ext = ext.lower()
    for folder, exts in rules.get("folders", {}).items():
        if ext in [e.lower() for e in exts]:
            return folder
    return rules.get("unknown_folder", "Other")


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    for i in range(2, 10_000):
        candidate = p.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find unique name for {p.name}")


def plan_actions(in_root: Path, out_root: Path, rules: dict, rename: bool) -> list[MovePlan]:
    """
    Build a list of actions from in_root -> out_root.
    If out_root == in_root: this becomes an in-place re-organization (moves).
    If out_root != in_root: this becomes a copy to a new organized folder (copies).
    """
    plans: list[MovePlan] = []

    # Which top-level folders count as "already organized"?
    organized_top_folders = set(rules.get("folders", {}).keys())
    unknown_folder = rules.get("unknown_folder", "Other")
    organized_top_folders.add(unknown_folder)

    for item in in_root.rglob("*"):
        if item.is_dir():
            continue
        if item.name.startswith("."):
            continue

        rel_parent = item.parent.relative_to(in_root)

        # If the source is already under a recognized bucket folder at top-level, skip it
        if len(rel_parent.parts) >= 1 and rel_parent.parts[0] in organized_top_folders:
            continue

        bucket = extension_bucket(item.suffix, rules)
        target_dir = out_root / bucket
        target_name = slugify(item.name) if rename else item.name
        target = unique_path(target_dir / target_name)

        plans.append(MovePlan(src=item, dst=target))

    return plans


def write_log(plans: list[MovePlan], log_path: Path) -> None:
    lines = [f"{p.src} -> {p.dst}" for p in plans]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def ensure_clean_output_folder(out_root: Path, in_place: bool) -> None:
    # If using a separate output folder, create it; if it exists and isn't empty, refuse.
    if in_place:
        return
    out_root.mkdir(parents=True, exist_ok=True)
    if any(out_root.iterdir()):
        raise SystemExit(
            f"Output folder is not empty: {out_root}\n"
            f"Please choose an empty folder or delete its contents first."
        )


def apply(plans: list[MovePlan], in_place: bool, dry_run: bool) -> None:
    if dry_run:
        return

    for p in plans:
        p.dst.parent.mkdir(parents=True, exist_ok=True)
        if in_place:
            shutil.move(str(p.src), str(p.dst))
        else:
            shutil.copy2(str(p.src), str(p.dst))


def main():
    ap = argparse.ArgumentParser(
        description="Organize files into folders by extension (safe-first)."
    )
    ap.add_argument("root", help="Input folder to organize")
    ap.add_argument("--rules", default="rules.json", help="Path to rules.json")
    ap.add_argument("--dry-run", action="store_true", help="Only preview; do not move/copy files")
    ap.add_argument("--rename", action="store_true", help="Slugify filenames (spaces -> _, remove weird chars)")
    ap.add_argument(
        "--output",
        help="Output folder for organized copy. If omitted, organizes in place (moves).",
        default=None,
    )
    args = ap.parse_args()

    in_root = Path(args.root).expanduser().resolve()
    rules_path = Path(args.rules).expanduser().resolve()

    if not in_root.exists() or not in_root.is_dir():
        raise SystemExit(f"Root folder not found or not a directory: {in_root}")
    if not rules_path.exists():
        raise SystemExit(f"Rules file not found: {rules_path}")

    out_root = Path(args.output).expanduser().resolve() if args.output else in_root
    in_place = (out_root == in_root)

    rules = load_rules(rules_path)

    # If output is separate, ensure it's empty to avoid mixing past runs
    ensure_clean_output_folder(out_root, in_place=in_place)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = Path.cwd() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"organize_log_{in_root.name}_to_{out_root.name}_{timestamp}.txt"

    plans = plan_actions(in_root, out_root, rules, rename=args.rename)
    write_log(plans, log_path)
    apply(plans, in_place=in_place, dry_run=args.dry_run)

    print(f"Planned actions: {len(plans)}")
    print(f"Log: {log_path}")
    if args.output:
        print(f"Mode: COPY to output folder ({out_root})")
    else:
        print("Mode: IN-PLACE move")
    if args.dry_run:
        print("Dry-run only. Re-run without --dry-run to apply.")


if __name__ == "__main__":
    main()
