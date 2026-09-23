"""End-to-end Manager mapping tests against a real PostProject production."""

from pathlib import Path

from openassetio.access import EntityTraitsAccess, ResolveAccess
from openassetio.hostApi import HostInterface, ManagerFactory
from openassetio.log import ConsoleLogger
from openassetio.pluginSystem import PythonPluginSystemManagerImplementationFactory
from openassetio_mediacreation.traits.content import LocatableContentTrait_v1
from openassetio_mediacreation.traits.timeDomain import FrameRangedTrait_v1
from postproject import ImageSequenceInput, Production, RepresentationKind


LocatableContentTrait = LocatableContentTrait_v1
FrameRangedTrait = FrameRangedTrait_v1


class FixtureHost(HostInterface):
    def identifier(self):
        return "org.postproject.tests.host"

    def displayName(self):
        return "PostProject Manager tests"


def create_manager(settings):
    logger = ConsoleLogger()
    factory = PythonPluginSystemManagerImplementationFactory(logger)
    manager = ManagerFactory.createManagerForInterface(
        "org.postproject.manager", FixtureHost(), factory, logger
    )
    manager.initialize(settings)
    return manager


def test_resolves_file_representation(tmp_path, native_library):
    media = tmp_path / "clip.mov"
    media.write_bytes(b"camera media")
    production_path = tmp_path / "production.pproj"
    with Production.create(production_path, library_path=native_library) as production:
        with production.transaction() as transaction:
            asset_id = transaction.import_media(media, "Camera A")
        representation = production.representations[asset_id][0]
        reference = production.host_bindings[representation.id]

    manager = create_manager(
        {"production_path": str(production_path), "library_path": native_library}
    )
    context = manager.createContext()
    data = manager.resolve(
        manager.createEntityReference(reference),
        {LocatableContentTrait.kId},
        ResolveAccess.kRead,
        context,
    )
    assert LocatableContentTrait(data).getLocation() == media.resolve().as_uri()


def test_image_sequence_remains_one_representation(tmp_path, native_library):
    sequence = tmp_path / "plates"
    sequence.mkdir()
    for frame in range(1001, 1004):
        (sequence / f"shot.{frame:04}.exr").write_bytes(f"frame {frame}".encode())
    production_path = tmp_path / "sequence.pproj"
    with Production.create(production_path, library_path=native_library) as production:
        with production.transaction() as transaction:
            seed = tmp_path / "seed.mov"
            seed.write_bytes(b"seed")
            asset_id = transaction.import_media(seed, "Shot")
            representation_id = transaction.add_image_sequence_representation(
                asset_id,
                RepresentationKind.ORIGINAL,
                ImageSequenceInput(
                    str(sequence), "shot.", ".exr", 4, 1001, 1003, 1, 24, 1
                ),
            )
        representation = next(
            item
            for item in production.representations[asset_id]
            if item.id == representation_id
        )
        assert len(representation.resources) == 1
        reference = production.host_bindings[representation.id]

    manager = create_manager(
        {"production_path": str(production_path), "library_path": native_library}
    )
    context = manager.createContext()
    entity = manager.createEntityReference(reference)
    traits = manager.entityTraits(entity, EntityTraitsAccess.kRead, context)
    assert FrameRangedTrait.kId in traits
    data = manager.resolve(
        entity,
        {LocatableContentTrait.kId, FrameRangedTrait.kId},
        ResolveAccess.kRead,
        context,
    )
    assert LocatableContentTrait(data).getLocation() == sequence.resolve().as_uri()
    assert FrameRangedTrait(data).getStartFrame() == 1001
    assert FrameRangedTrait(data).getEndFrame() == 1003


def pytest_generate_tests(metafunc):
    if "native_library" in metafunc.fixturenames:
        import os

        metafunc.parametrize("native_library", [os.environ["POSTPROJECT_LIBRARY"]])
