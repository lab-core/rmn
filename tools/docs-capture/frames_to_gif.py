"""Turn the frames recorded by capture.mjs into the GIFs of the user guide.

It also shrinks the PNG screenshots in --out: 256 colours are plenty for
the flat colours of the UI, and divide their size by about three.

Each animation is a directory of frames/<name> with a manifest.json listing
its frames and how long each one shows. A GIF plays on GitHub and in the app
alike, which a video file in the repository would not.

Usage::

    IMG=../../services/webapp/ng/src/assets/guide/img
    python frames_to_gif.py --frames frames --out $IMG
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

# the overview strings a few frames of each step together
OVERVIEW = {
    "template-editor": [0, 2, -1],
    "nouvelle-tache": [0, 2, 4, 6, -1],
    "matricules": [0, 1, -1],
    "correction": [0, 1, 2, -1],
}


def load(directory: Path, width: int) -> list[tuple[Image.Image, int]]:
    """Read the frames of one animation, scaled to `width` pixels.

    Args:
        directory: The directory of the frames and their manifest.
        width: The width of the GIF.

    Returns:
        Each frame with its duration in milliseconds.
    """
    manifest = json.loads((directory / "manifest.json").read_text())
    frames = []
    for entry in manifest:
        image = Image.open(directory / Path(entry["file"]).name).convert("RGB")
        height = round(image.height * width / image.width)
        frames.append((image.resize((width, height), Image.LANCZOS), entry["ms"]))
    return frames


def save(frames: list[tuple[Image.Image, int]], path: Path) -> None:
    """Write `frames` as a looping GIF with one shared palette.

    Args:
        frames: The images and their durations.
        path: The GIF to write.
    """
    # one adaptive palette for the whole animation: the UI has few colours,
    # and a palette per frame makes the flat backgrounds flicker
    palette = frames[0][0].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    images = [
        image.quantize(palette=palette, dither=Image.Dither.NONE) for image, _ in frames
    ]
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=[ms for _, ms in frames],
        loop=0,
        optimize=True,
        disposal=1,
    )
    print(f"{path.name}: {len(images)} frames, {path.stat().st_size // 1024} KB")


def shrink(path: Path, width: int) -> None:
    """Rewrite the screenshot `path` at most `width` pixels wide, 256 colours.

    Args:
        path: The PNG to rewrite in place.
        width: The largest width to keep.
    """
    image = Image.open(path).convert("RGB")
    if image.width > width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.LANCZOS)
    image.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(
        path, optimize=True
    )


def main() -> None:
    """Write one GIF per recorded animation, plus the overview."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    here = Path(__file__).resolve().parent
    parser.add_argument("--frames", type=Path, default=here / "frames")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--width", type=int, default=960)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for png in sorted(args.out.glob("*.png")):
        shrink(png, 1280)
    recorded = {}
    for directory in sorted(args.frames.iterdir()):
        if (directory / "manifest.json").exists():
            recorded[directory.name] = load(directory, args.width)
            save(recorded[directory.name], args.out / f"{directory.name}.gif")

    overview = []
    for name, picks in OVERVIEW.items():
        frames = recorded.get(name, [])
        overview += [
            (frames[i][0], 1600)
            for i in picks
            if frames and -len(frames) <= i < len(frames)
        ]
    # and ends on the files to hand back to Moodle
    final = args.out / "fichiers.png"
    if overview and final.exists():
        image = Image.open(final).convert("RGB")
        height = round(image.height * args.width / image.width)
        overview.append((image.resize((args.width, height), Image.LANCZOS), 3000))
    if overview:
        save(overview, args.out / "parcours.gif")


if __name__ == "__main__":
    main()
