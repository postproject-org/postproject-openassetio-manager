"""Run inside licensed Nuke 17.0v1; no mock result is commercial evidence."""

import hashlib
import json
import os
import platform
import shutil
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def run():
    import _asset
    import nuke
    import openassetio
    import openassetio_mediacreation
    from openassetio.access import ResolveAccess
    from openassetio.errors import BatchElementException

    from postproject_openassetio.traits import FrameRangedTrait, LocatableContentTrait

    if nuke.NUKE_VERSION_STRING != "17.0v1" or platform.python_version_tuple()[:2] != (
        "3",
        "11",
    ):
        raise RuntimeError("this prepared trial requires Nuke 17.0v1 / CPython 3.11")
    if openassetio.versionString() != "1.0.0":
        raise RuntimeError("use Nuke's bundled OpenAssetIO 1.0.0")
    try:
        mediacreation_version = version("openassetio-mediacreation")
    except PackageNotFoundError:
        mediacreation_version = None
    if mediacreation_version not in (None, "1.0.0a12"):
        raise RuntimeError("use Nuke's bundled MediaCreation alpha.12")
    manifest = json.loads(Path(os.environ["POSTPROJECT_NUKE_FIXTURE"]).read_text())
    output = Path(os.environ["POSTPROJECT_NUKE_OUTPUT"]).resolve()
    output.mkdir()  # Never replace an existing comp or acceptance report.
    reference = manifest["reference"]
    original, relocated, duplicate = (
        Path(manifest[key]) for key in ("original", "relocated", "duplicate")
    )
    managed = output / "managed.nk"
    flattened = output / "render-copy.nk"

    def setup(name):
        _asset.setupManager(manifest["configs"][name])

    def resolve():
        manager = _asset.getManager()
        return manager.resolve(
            manager.createEntityReference(reference),
            {LocatableContentTrait.kId, FrameRangedTrait.kId},
            ResolveAccess.kRead,
            _asset.getContext(),
        )

    def read_node():
        return nuke.toNode("PostProjectRead")

    def assert_read(directory):
        read = read_node()
        assert read["file"].getValue() == reference
        for knob in ("first", "origfirst"):
            assert read[knob].value() == manifest["first"]
        for knob in ("last", "origlast"):
            assert read[knob].value() == manifest["last"]
        evaluated = read["file"].getEvaluatedValue()
        if "{frame" in evaluated:
            raise RuntimeError(
                "Nuke did not expand the documented OpenAssetIO frame template; native sequence ingest is unqualified"
            )
        assert str(directory) in evaluated
        nuke.frame(manifest["first"])
        assert read.width() == 16 and read.height() == 16

    moved = copied = False
    try:
        setup("normal")
        data = resolve()
        assert FrameRangedTrait(data).getStartFrame() == manifest["first"]
        assert FrameRangedTrait(data).getEndFrame() == manifest["last"]
        nuke.scriptClear()
        read = nuke.nodes.Read(name="PostProjectRead")
        read["file"].setValue(reference)
        for knob in ("first", "origfirst"):
            read[knob].setValue(manifest["first"])
        for knob in ("last", "origlast"):
            read[knob].setValue(manifest["last"])
        nuke.root()["fps"].setValue(manifest["rate"][0] / manifest["rate"][1])
        assert_read(original)
        nuke.scriptSaveAs(str(managed), overwrite=1)
        nuke.scriptClear()
        nuke.scriptOpen(str(managed))
        assert_read(original)
        original.rename(relocated)
        moved = True
        setup("relocated")
        nuke.scriptClear()
        nuke.scriptOpen(str(managed))
        assert_read(relocated)
        shutil.copytree(relocated, duplicate)
        copied = True
        for variant in ("ambiguous", "missing"):
            setup(variant)
            try:
                resolve()
            except BatchElementException:
                pass
            else:
                raise AssertionError(f"{variant} resolution silently selected content")
            assert read_node()["file"].getValue() == reference
        shutil.rmtree(duplicate)
        copied = False
        relocated.rename(original)
        moved = False
        setup("normal")
        nuke.scriptClear()
        nuke.scriptOpen(str(managed))
        nuke.scriptSaveAs(str(flattened), overwrite=1)
        complete, unresolved = nuke.deassetize([read_node()])
        assert complete and not unresolved
        assert (
            not read_node()["file"]
            .getValue()
            .startswith("https://postproject.org/ref/")
        )
        nuke.scriptSaveAs(str(flattened), overwrite=1)
        _asset.clearManager()
        nuke.scriptClear()
        nuke.scriptOpen(str(flattened))
        assert read_node().width() == 16
        setup("normal")
        nuke.scriptClear()
        nuke.scriptOpen(str(managed))
        assert_read(original)  # The canonical original was never deassetized.
        module_path = Path(openassetio_mediacreation.__file__)
        report = {
            "result": "passed",
            "scope": "licensed headless Read ingestion",
            "nuke": nuke.NUKE_VERSION_STRING,
            "python": platform.python_version(),
            "openassetio": openassetio.versionString(),
            "mediacreation_declared_bundle": "1.0.0a12",
            "mediacreation_distribution": mediacreation_version,
            "mediacreation_module_sha256": hashlib.sha256(
                module_path.read_bytes()
            ).hexdigest(),
            "postproject": version("postproject"),
            "manager": version("postproject-openassetio-manager"),
            "reference": reference,
            "managed_copy": str(managed),
            "render_copy": str(flattened),
        }
        (output / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    finally:
        if copied:
            shutil.rmtree(duplicate)
        if moved:
            relocated.rename(original)


if __name__ == "__main__":
    run()
