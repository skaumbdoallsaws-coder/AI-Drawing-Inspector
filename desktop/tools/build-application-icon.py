"""Convert the existing web header logo to a multi-resolution Windows icon."""

from pathlib import Path

from PIL import Image


def main():
    project = Path(__file__).resolve().parents[2]
    destination = project / "desktop/assets/inspectorpro.ico"
    sizes = [(size, size) for size in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
    with Image.open(project / "static/logo.png") as source:
        logo = source.convert("RGBA")
        if logo.width != logo.height or logo.width < 256:
            raise ValueError("The header logo must be square and at least 256px.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        logo.save(destination, format="ICO", sizes=sizes)
    with Image.open(destination) as icon:
        if icon.ico.sizes() != set(sizes):
            raise ValueError("The Windows icon is missing required sizes.")
    print(destination)


if __name__ == "__main__":
    main()
