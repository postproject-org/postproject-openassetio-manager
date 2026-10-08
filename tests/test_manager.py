"""End-to-end Manager mapping tests against a real PostProject production."""

from fractions import Fraction
from pathlib import Path

from openassetio.access import EntityTraitsAccess, ResolveAccess
from openassetio.hostApi import HostInterface, ManagerFactory
from openassetio.log import ConsoleLogger
from openassetio.pluginSystem import PythonPluginSystemManagerImplementationFactory
from openassetio_mediacreation.traits.content import LocatableContentTrait_v1
from openassetio_mediacreation.specifications.twoDimensional import (
    BitmapImageResourceSequenceSpecification_v1,
)
from openassetio_mediacreation.traits.timeDomain import FrameRangedTrait_v1
from openassetio_mediacreation.traits.twoDimensional import PixelBasedTrait_v1
from postproject import ResourceRef, RepresentationRef, ImageSequenceSource, Production, RepresentationKind, SequenceNaming


LocatableContentTrait = LocatableContentTrait_v1
FrameRangedTrait = FrameRangedTrait_v1
PixelBasedTrait = PixelBasedTrait_v1
BitmapImageResourceSequenceSpecification = BitmapImageResourceSequenceSpecification_v1


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
            transaction.commit()
        representation = production.representations[asset_id][0]
        reference = production.host_bindings[RepresentationRef(representation.id)]

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


def test_resolves_media_added_after_initialization(tmp_path, native_library):
    production_path = tmp_path / "production.pproj"
    Production.create(production_path, library_path=native_library).close()
    manager = create_manager(
        {"production_path": str(production_path), "library_path": native_library}
    )

    media = tmp_path / "late.mov"
    media.write_bytes(b"late media")
    with Production.open(production_path, library_path=native_library) as production:
        with production.transaction() as transaction:
            asset_id = transaction.import_media(media, "Late")
            transaction.commit()
        representation = production.representations[asset_id][0]
        references = [
            production.host_bindings[RepresentationRef(representation.id)],
            production.host_bindings[ResourceRef(representation.resources[0].id)],
        ]

    context = manager.createContext()
    for reference in references:
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
            asset_id = transaction.import_media(
                ImageSequenceSource(
                    sequence, SequenceNaming("shot.", ".exr", 4), 1001, 1003, 1, Fraction(24)
                ),
                "Shot",
            )
            transaction.commit()
        # The sequence is the asset's only original representation.
        (representation,) = production.representations[asset_id]
        assert representation.kind is RepresentationKind.ORIGINAL
        assert len(representation.resources) == 1
        reference = production.host_bindings[RepresentationRef(representation.id)]

    manager = create_manager(
        {"production_path": str(production_path), "library_path": native_library}
    )
    context = manager.createContext()
    entity = manager.createEntityReference(reference)
    traits = manager.entityTraits(entity, EntityTraitsAccess.kRead, context)
    assert BitmapImageResourceSequenceSpecification.kTraitSet - {PixelBasedTrait.kId} <= traits
    data = manager.resolve(
        entity,
        {LocatableContentTrait.kId, FrameRangedTrait.kId},
        ResolveAccess.kRead,
        context,
    )
    location = LocatableContentTrait(data)
    assert location.getLocation() == f"{sequence.resolve().as_uri()}/shot.%7Bframe%3A04d%7D.exr"
    assert location.getIsTemplated() is True
    assert FrameRangedTrait(data).getStartFrame() == 1001
    assert FrameRangedTrait(data).getEndFrame() == 1003

    # Graded and renamed frames are relinked by content; the template then
    # names the frames as they are called at the resolved location.
    graded = tmp_path / "graded"
    graded.mkdir()
    for frame in range(1001, 1004):
        (sequence / f"shot.{frame:04}.exr").rename(graded / f"shot-graded_{frame:04}.exr")
    with Production.open(production_path, library_path=native_library) as production:
        (resolution,) = production.resolve(asset_id, search_directories=[graded])
        (resource,) = resolution.resources
        (candidate,) = resource.candidates
        with production.transaction() as transaction:
            transaction.confirm_locator(
                resource.resource_id,
                candidate.uri,
                media_root=candidate.media_root,
                sequence_naming=candidate.sequence_naming,
            )
            transaction.commit()
    data = manager.resolve(
        entity, {LocatableContentTrait.kId}, ResolveAccess.kRead, context
    )
    assert LocatableContentTrait(data).getLocation() == (
        f"{graded.resolve().as_uri()}/shot-graded_%7Bframe%3A04d%7D.exr"
    )
