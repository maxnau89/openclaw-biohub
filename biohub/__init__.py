"""biohub — CLI for managing openclaw-biohub adapters.

Available subcommands (see `biohub --help`):

  list-adapters     Show all adapters and whether each is configured.
  connect <slug>    Walk through credential setup for an adapter.
  sync <slug>       Pull data from one adapter into its raw DB and roll
                    up into health.db.
  sync --all        Sync every configured adapter.

The CLI is registered as a script via pyproject.toml; install with
`pip install -e .` from the repo root to get the `biohub` command.
"""
__version__ = "0.2.0"
