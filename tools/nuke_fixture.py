"""Create three deterministic PNG frames and a public-API production fixture."""

import argparse
import json
import struct
import zlib
from fractions import Fraction
from pathlib import Path

from postproject import (
    ImageSequenceSource,
    Production,
    RepresentationRef,
    SequenceNaming,
)


def png(frame):
    """Small RGB PNG using W3C PNG IHDR/IDAT/IEND and filter zero."""

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixel = bytes((frame - 1000, 40, 80))
    scanlines = (b"\0" + pixel * 16) * 16
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )


def write_config(path, production, library, root):
    settings = {
        "production_path": str(production),
        "library_path": str(library),
        "root.plates": str(root),
    }
    lines = [
        "[manager]",
        'identifier = "org.postproject.manager"',
        "",
        "[manager.settings]",
    ]
    lines.extend(
        f"{json.dumps(key)} = {json.dumps(value)}" for key, value in settings.items()
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_fixture(destination, library):
    destination = Path(destination).resolve()
    library = Path(library).resolve(strict=True)
    destination.mkdir()  # A new destination; repeated runs never overwrite work.
    media = destination / "media"
    original = media / "plates"
    original.mkdir(parents=True)
    for frame in range(1001, 1004):
        (original / f"plate.{frame:04d}.png").write_bytes(png(frame))
    production_path = destination / "production.pproj"
    with Production.create(production_path, library_path=library) as production:
        with production.transaction() as transaction:
            transaction.add_media_root("plates", "Nuke fixture")
            asset_id = transaction.import_media(
                ImageSequenceSource(
                    original,
                    SequenceNaming("plate.", ".png", 4),
                    1001,
                    1003,
                    1,
                    Fraction(24),
                ),
                "Three-frame PNG fixture",
            )
            transaction.commit()
        representation = production.representations[asset_id][0]
        reference = production.host_bindings[RepresentationRef(representation.id)]
        production_id = str(production.id)
    roots = {
        "normal": original,
        "relocated": media / "relocated",
        "ambiguous": media,
        "missing": destination / "empty",
    }
    roots["missing"].mkdir()
    configs = {}
    for name, root in roots.items():
        config = destination / f"{name}.toml"
        write_config(config, production_path, library, root)
        configs[name] = str(config)
    manifest = {
        "format_version": 1,
        "production": str(production_path),
        "production_id": production_id,
        "reference": reference,
        "library": str(library),
        "first": 1001,
        "last": 1003,
        "rate": [24, 1],
        "original": str(original),
        "relocated": str(roots["relocated"]),
        "duplicate": str(media / "duplicate"),
        "configs": configs,
    }
    path = destination / "fixture.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--library", type=Path, required=True)
    args = parser.parse_args()
    print(create_fixture(args.destination, args.library))
