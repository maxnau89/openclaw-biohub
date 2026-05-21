"""biohub CLI entry point — see `biohub --help`."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_cls
from typing import Sequence

from . import body_comp
from .registry import ADAPTERS, all_adapters, get_adapter


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _stability_marker(s: str) -> str:
    return {
        "stable": "stable",
        "beta": "beta",
        "experimental": "EXPERIMENTAL",
    }.get(s, s)


def _is_configured(adapter) -> bool:
    return adapter.secrets_path.exists()


def _print_table(rows: list[list[str]], headers: list[str]) -> None:
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows:
        print(fmt.format(*r))


# ─── Subcommands ─────────────────────────────────────────────────────────────


def cmd_list_adapters(args: argparse.Namespace) -> int:
    rows: list[list[str]] = []
    for a in all_adapters():
        rows.append([
            a.slug,
            a.display_name,
            _stability_marker(a.stability),
            "yes" if _is_configured(a) else "no",
        ])
    _print_table(rows, ["slug", "name", "stability", "configured"])
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    try:
        adapter = get_adapter(args.slug)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if adapter.stability == "experimental":
        print(
            f"⚠️  WARNING: the `{adapter.slug}` adapter is EXPERIMENTAL — its\n"
            f"   upstream library / API access can break without notice.\n"
        )

    print(adapter.setup_instructions())
    if args.dry_run:
        print("\n(--dry-run: stopping here; no credentials written)")
        return 0

    print()
    adapter.configure_interactive()

    print("\nRunning a sanity sync (limit 1 record per resource)…")
    try:
        result = adapter.sync(limit=1)
        print(f"  sync: {result}")
        adapter.rollup_to_health_db()
        print("  rollup: ok")
    except Exception as e:
        print(f"  sanity sync hit an error: {e}", file=sys.stderr)
        print("  Credentials are saved; you can retry with `biohub sync " + adapter.slug + "`.")
        return 1

    print(
        f"\n✓ Done. Schedule a recurring sync (cron / systemd timer):\n"
        f"    biohub sync {adapter.slug}"
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    if args.all:
        configured = [a for a in all_adapters() if _is_configured(a)]
        if not configured:
            print(
                "No adapters are configured yet. Run `biohub connect <slug>` "
                "for the one(s) you want.",
                file=sys.stderr,
            )
            return 1
        targets = configured
    else:
        if not args.slug:
            print("error: provide a slug or pass --all", file=sys.stderr)
            return 2
        try:
            targets = [get_adapter(args.slug)]
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    exit_code = 0
    for adapter in targets:
        marker = " (EXPERIMENTAL)" if adapter.stability == "experimental" else ""
        print(f"\n=== {adapter.display_name}{marker} ===")
        if not _is_configured(adapter):
            print(f"  Not configured. Run: biohub connect {adapter.slug}")
            exit_code = 1
            continue
        if args.dry_run:
            print(f"  (--dry-run: would sync; skipping network/IO)")
            continue
        try:
            result = adapter.sync(since=args.since)
            print(f"  sync: {result}")
            n = adapter.rollup_to_health_db()
            print(f"  rollup: {n} rows into daily_metrics")
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            exit_code = 1

    return exit_code


# ─── log-measurement / log-phase ─────────────────────────────────────────────


_SKINFOLD_SITES = (
    "chest", "abdominal", "thigh", "tricep",
    "subscapular", "suprailiac", "midaxillary",
)


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"  {label}{suffix}: ").strip()
    if not val and default is not None:
        return default
    return val


def _prompt_float(label: str, default: float | None = None) -> float | None:
    """Returns None if the user enters an empty value and no default is given."""
    raw = _prompt(label, default=None if default is None else str(default))
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        print(f"  ! not a number: {raw!r} — leaving empty")
        return None


def cmd_log_measurement(args: argparse.Namespace) -> int:
    """Log a body-composition entry. Supports flag-based + interactive modes."""
    today = date_cls.today().isoformat()

    if args.non_interactive or args.weight is not None or args.body_fat_pct is not None \
            or any(getattr(args, s) is not None for s in _SKINFOLD_SITES):
        # Flag-driven path
        date_str = args.date or today
        method = args.method
        weight = args.weight
        bf_pct = args.body_fat_pct
        sites = {s: getattr(args, s) for s in _SKINFOLD_SITES if getattr(args, s) is not None}
    else:
        # Interactive path
        print("biohub log-measurement — enter a body-composition snapshot")
        print(f"(press Enter to skip a field)\n")
        date_str = _prompt("date (YYYY-MM-DD)", default=today)
        method = _prompt("method", default=args.method)
        weight = _prompt_float("weight (kg)")
        bf_pct_raw = _prompt_float("body_fat_pct (leave blank to compute from skinfolds)")
        bf_pct = bf_pct_raw
        sites = {}
        if method.startswith("jackson-pollock-7"):
            print("\nSkinfold sites (mm):")
            for s in _SKINFOLD_SITES:
                v = _prompt_float(s)
                if v is not None:
                    sites[s] = v

    # Compute body fat from skinfolds if not supplied
    if bf_pct is None and len(sites) == 7 and method.startswith("jackson-pollock-7"):
        sex = args.sex
        age = args.age
        if sex is None or age is None:
            if args.non_interactive:
                print("error: --sex and --age required to compute body fat from skinfolds",
                      file=sys.stderr)
                return 2
            sex = sex or _prompt("sex (m/f)", default="m")
            age_raw = _prompt("age (years)")
            try:
                age = int(age_raw)
            except (TypeError, ValueError):
                print(f"error: invalid age {age_raw!r}", file=sys.stderr)
                return 2
        try:
            bf_pct = body_comp.compute_bf_jp7(sites, sex, age)
            print(f"  computed body_fat_pct = {bf_pct}", file=sys.stderr)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    lean = fat = None
    if weight is not None and bf_pct is not None:
        lean, fat = body_comp.derive_mass(weight, bf_pct)

    try:
        result = body_comp.log_measurement(
            date=date_str,
            method=method,
            weight_kg=weight,
            body_fat_pct=bf_pct,
            lean_mass_kg=lean,
            fat_mass_kg=fat,
            skinfolds=sites or None,
            notes=args.notes,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_log_phase_start(args: argparse.Namespace) -> int:
    try:
        result = body_comp.start_phase(
            name=args.name,
            category=args.category,
            start_date=args.start,
            color=args.color,
            notes=args.notes,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_log_phase_end(args: argparse.Namespace) -> int:
    try:
        result = body_comp.end_phase(
            name=args.name,
            end_date=args.end,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if result.get("action") == "no-match":
        print(f"  no open phase named {args.name!r}", file=sys.stderr)
        print(json.dumps(result, indent=2, default=str))
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_log_phase_list(args: argparse.Namespace) -> int:
    try:
        rows = body_comp.list_phases(only_open=args.open_only)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not rows:
        print("  (no phases)")
        return 0
    table = [[
        str(r["id"]),
        r["name"],
        r["category"] or "",
        r["start_date"],
        r["end_date"] or "(open)",
        r.get("color") or "",
    ] for r in rows]
    _print_table(table, ["id", "name", "category", "start", "end", "color"])
    return 0


# ─── Entry point ─────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="biohub",
        description="openclaw-biohub: multi-device personal-health hub CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "list-adapters",
        help="Show all adapters and whether each is configured.",
    )

    p_conn = sub.add_parser(
        "connect",
        help="Walk through credential setup for an adapter.",
    )
    p_conn.add_argument("slug", help=f"one of: {', '.join(ADAPTERS)}")
    p_conn.add_argument(
        "--dry-run", action="store_true",
        help="Show setup instructions but don't prompt for credentials.",
    )

    p_sync = sub.add_parser(
        "sync",
        help="Pull data from one (or all) configured adapter(s).",
    )
    p_sync.add_argument(
        "slug", nargs="?",
        help=f"one of: {', '.join(ADAPTERS)} (omit if using --all)",
    )
    p_sync.add_argument(
        "--all", action="store_true",
        help="Sync every configured adapter.",
    )
    p_sync.add_argument(
        "--since", metavar="YYYY-MM-DD",
        help="Start date (defaults to the adapter's last-synced date).",
    )
    p_sync.add_argument(
        "--dry-run", action="store_true",
        help="Skip network calls; just print what would happen.",
    )

    # log-measurement
    p_meas = sub.add_parser(
        "log-measurement",
        help="Log a body-composition entry (caliper / scale / DEXA / manual).",
    )
    p_meas.add_argument("--date", help="YYYY-MM-DD (default: today)")
    p_meas.add_argument(
        "--method", default="jackson-pollock-7",
        help="jackson-pollock-7 | jackson-pollock-3 | scale | dexa | manual",
    )
    p_meas.add_argument("--weight", type=float, help="body weight in kg")
    p_meas.add_argument(
        "--body-fat-pct", type=float, dest="body_fat_pct",
        help="body-fat %% (computed from skinfolds if omitted)",
    )
    for site in _SKINFOLD_SITES:
        p_meas.add_argument(f"--{site}", type=float, help=f"{site} skinfold in mm")
    p_meas.add_argument("--sex", choices=["m", "f"], help="for Jackson-Pollock formula")
    p_meas.add_argument("--age", type=int, help="for Jackson-Pollock formula")
    p_meas.add_argument("--notes", help="free-form notes")
    p_meas.add_argument(
        "--non-interactive", action="store_true",
        help="Fail instead of prompting when flags are missing.",
    )
    p_meas.add_argument(
        "--dry-run", action="store_true",
        help="Print the row that would be inserted; don't touch the DB.",
    )

    # log-phase
    p_phase = sub.add_parser(
        "log-phase",
        help="Manage tracking phases (bulks, cuts, supplements, …).",
    )
    phase_sub = p_phase.add_subparsers(dest="phase_cmd", required=True)

    p_start = phase_sub.add_parser("start", help="Open a new tracking phase.")
    p_start.add_argument(
        "category",
        help="training | diet | supplement | medication | lifestyle | <custom>",
    )
    p_start.add_argument("name", help="phase name (e.g. 'Spring Cut')")
    p_start.add_argument("--color", help="hex color for UI chip (e.g. #fbbf24)")
    p_start.add_argument("--start", metavar="YYYY-MM-DD", help="default: today")
    p_start.add_argument("--notes", help="free-form notes")
    p_start.add_argument("--dry-run", action="store_true")

    p_end = phase_sub.add_parser("end", help="Close the most recent open phase by name.")
    p_end.add_argument("name")
    p_end.add_argument("--end", metavar="YYYY-MM-DD", help="default: today")
    p_end.add_argument("--dry-run", action="store_true")

    p_list = phase_sub.add_parser("list", help="Show tracking phases.")
    p_list.add_argument(
        "--open-only", action="store_true", dest="open_only",
        help="Only show currently-open phases.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "list-adapters":
        return cmd_list_adapters(args)
    if args.cmd == "connect":
        return cmd_connect(args)
    if args.cmd == "sync":
        return cmd_sync(args)
    if args.cmd == "log-measurement":
        return cmd_log_measurement(args)
    if args.cmd == "log-phase":
        if args.phase_cmd == "start":
            return cmd_log_phase_start(args)
        if args.phase_cmd == "end":
            return cmd_log_phase_end(args)
        if args.phase_cmd == "list":
            return cmd_log_phase_list(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
