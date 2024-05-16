"""Command-line interface."""

import click


@click.command()
@click.version_option()
def main() -> None:
    """CLI."""
    pass


if __name__ == "__main__":
    main(prog_name="CLI")  # pragma: no cover
