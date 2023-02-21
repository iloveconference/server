"""Command-line interface."""
import click


@click.command()
@click.version_option()
def main() -> None:
    """Server."""
    pass


if __name__ == "__main__":
    main(prog_name="server")  # pragma: no cover
