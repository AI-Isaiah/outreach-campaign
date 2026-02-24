import typer

app = typer.Typer(
    name="outreach",
    help="Multi-channel outreach campaign manager",
)


@app.callback()
def main() -> None:
    """Outreach Campaign CLI - manage contacts, campaigns, and sends."""


if __name__ == "__main__":
    app()
