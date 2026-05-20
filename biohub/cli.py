"""biohub CLI entry point — see `biohub --help`."""
from __future__ import annotations

import argparse
import sys
from typing import Sequence

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
    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
