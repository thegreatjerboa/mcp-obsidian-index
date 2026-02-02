from collections.abc import Sequence
from pathlib import Path

import click

from obsidian_index.index.models import SUPPORTED_MODELS, get_model_config


@click.group("obsidian-index")
def main():
    """
    CLI for Obsidian Index.
    """
    pass


@main.command("mcp")
@click.option(
    "--database",
    "-d",
    "database_path",
    help="Path to the database.",
    required=True,
    type=click.Path(dir_okay=False, file_okay=True, path_type=Path),
)
@click.option(
    "--vault",
    "-v",
    "vault_paths",
    multiple=True,
    help="Vault to index.",
    required=True,
    type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path),
)
@click.option("--reindex", is_flag=True, help="Reindex all notes.")
@click.option("--watch", is_flag=True, help="Watch for changes.")
@click.option(
    "--model",
    "-m",
    "model_name",
    help=f"Embedding model to use. Overrides OBSIDIAN_INDEX_MODEL env var. Supported: {', '.join(SUPPORTED_MODELS.keys())}",
    type=click.Choice(list(SUPPORTED_MODELS.keys())),
    default=None,
)
def mcp_cmd(
    database_path: Path,
    vault_paths: Sequence[Path],
    reindex: bool,
    watch: bool,
    model_name: str | None,
):
    """
    Run the Obsidian Index MCP server.
    """
    from obsidian_index.mcp_server import run_server

    model_config = get_model_config(model_name)

    run_server(
        {vault_path.name: vault_path for vault_path in vault_paths},
        database_path,
        enqueue_all=reindex,
        watch_directories=watch,
        ingest_batch_size=8,
        model_config=model_config,
    )


if __name__ == "__main__":
    main()
