"""End-to-end OpenAssetIO publishing into a real PostProject production."""

import json
import subprocess
import sys
import textwrap

import pytest
from openassetio.access import (
    EntityTraitsAccess,
    PolicyAccess,
    PublishingAccess,
    ResolveAccess,
)
from openassetio.errors import BatchElementError, BatchElementException
from openassetio.trait import TraitsData
from openassetio_mediacreation.traits.managementPolicy import ManagedTrait
from postproject import (
    AssetRef,
    ContentStructureKind,
    JobRef,
    JobState,
    Production,
    RepresentationKind,
    RepresentationRef,
)
from test_manager import create_manager

from postproject_openassetio.traits import (
    BitmapImageResourceSequenceSpecification,
    FrameRangedTrait,
    LocatableContentTrait,
    PixelBasedTrait,
    ProxyTrait,
)

SequenceSpecification = BitmapImageResourceSequenceSpecification

OBSERVER = textwrap.dedent(
    """
    import json, sys
    from postproject import Production, RepresentationAddedEvent

    path, library, after = sys.argv[1], sys.argv[2], int(sys.argv[3])
    with Production.open(path, library_path=library) as production:
        waiter = production.revision_waiter()
        while True:
            wait = waiter.wait(after, timeout=60)
            if not wait.revisions:
                print(json.dumps({"result": wait.result.value}))
                break
            added = [
                str(event.payload.representation_id)
                for revision in wait.revisions
                for event in production.revision_events[revision.id]
                if isinstance(event.payload, RepresentationAddedEvent)
            ]
            if added:
                print(json.dumps({"result": "revisions", "added": added}))
                break
            after = wait.revisions[-1].sequence
    """
)


@pytest.fixture
def production_with_shot(tmp_path, native_library):
    seed = tmp_path / "plate.mov"
    seed.write_bytes(b"camera plate")
    path = tmp_path / "publish.pproj"
    with Production.create(path, library_path=native_library) as production:
        with production.transaction() as transaction:
            asset_id = transaction.import_media(seed, "sh010")
            transaction.commit()
        reference = production.host_bindings[AssetRef(asset_id)]
    return path, asset_id, reference


def rendered_sequence(tmp_path):
    renders = tmp_path / "renders"
    renders.mkdir()
    for frame in range(1001, 1004):
        (renders / f"sh010.{frame:04}.exr").write_bytes(f"render {frame}".encode())
    return renders


def sequence_traits(location=None):
    specification = SequenceSpecification.create()
    frames = specification.frameRangedTrait()
    frames.setStartFrame(1001)
    frames.setEndFrame(1003)
    frames.setFramesPerSecond(24000 / 1001)
    specification.locatableContentTrait().setMimeType("image/x-exr")
    if location is not None:
        content = specification.locatableContentTrait()
        content.setLocation(location)
        content.setIsTemplated(True)
    return specification.traitsData()


def test_publishes_exr_sequence_as_one_representation(
    tmp_path, native_library, production_with_shot
):
    path, asset_id, asset_reference = production_with_shot
    manager = create_manager(
        {"production_path": str(path), "library_path": native_library}
    )
    context = manager.createContext()

    policy = manager.managementPolicy(
        SequenceSpecification.kTraitSet, PolicyAccess.kWrite, context
    )
    assert ManagedTrait.isImbuedTo(policy)
    asset_entity = manager.createEntityReference(asset_reference)
    required = manager.entityTraits(asset_entity, EntityTraitsAccess.kWrite, context)
    assert required == {LocatableContentTrait.kId}

    working = manager.preflight(
        asset_entity, sequence_traits(), PublishingAccess.kWrite, context
    )
    assert working.toString() != asset_reference
    with Production.open(path, library_path=native_library) as production:
        (job,) = production.jobs(limit=10).items
        assert job.state == JobState.REQUESTED
        assert job.output_asset_id == asset_id
        assert job.output_representation_kind == RepresentationKind.DERIVED
        after = production.latest_revision.sequence

    observer = subprocess.Popen(
        [sys.executable, "-c", OBSERVER, str(path), native_library, str(after)],
        stdout=subprocess.PIPE,
        text=True,
    )
    renders = rendered_sequence(tmp_path)
    location = f"{renders.resolve().as_uri()}/sh010.%7Bframe%3A04d%7D.exr"
    final = manager.register(
        working, sequence_traits(location), PublishingAccess.kWrite, context
    )
    observed = json.loads(observer.communicate(timeout=90)[0])

    with Production.open(path, library_path=native_library) as production:
        binding = production.host_bindings.parse(final.toString())
        assert isinstance(binding.object, RepresentationRef)
        representation_id = binding.object.id
        assert observed == {"result": "revisions", "added": [str(representation_id)]}

        representation = production.representation(representation_id)
        assert representation.asset_id == asset_id
        assert representation.kind == RepresentationKind.DERIVED
        assert representation.structure_kind == ContentStructureKind.IMAGE_SEQUENCE
        assert len(representation.resources) == 1
        sequence = representation.image_sequence
        assert (sequence.start, sequence.end) == (1001, 1003)
        (locator,) = representation.resources[0].locators
        assert locator.sequence_naming.padding == 4
        assert (sequence.rate_numerator, sequence.rate_denominator) == (24000, 1001)

        (activity,) = production.activities_producing[representation_id]
        assert activity.kind == "org.postproject:openassetio-publish"
        assert activity.inputs == ()
        assert activity.tool.name == "PostProject Manager tests"
        (job,) = production.jobs(limit=10).items
        assert JobRef(job.id) == production.host_bindings.parse(working.toString()).object
        assert job.state == JobState.SUCCEEDED
        assert job.completion.representation_id == representation_id
        assert job.completion.activity_id == activity.id

    traits = manager.entityTraits(final, EntityTraitsAccess.kRead, context)
    assert SequenceSpecification.kTraitSet <= traits
    data = manager.resolve(
        final,
        {LocatableContentTrait.kId, FrameRangedTrait.kId, PixelBasedTrait.kId},
        ResolveAccess.kRead,
        context,
    )
    content = LocatableContentTrait(data)
    assert content.getLocation() == location
    assert content.getIsTemplated() is True
    assert content.getMimeType() == "image/x-exr"
    assert PixelBasedTrait.isImbuedTo(data)
    assert FrameRangedTrait(data).getEndFrame() == 1003

    with pytest.raises(BatchElementException) as error:
        manager.register(
            working, sequence_traits(location), PublishingAccess.kWrite, context
        )
    assert error.value.error.code == BatchElementError.ErrorCode.kEntityAccessError


def test_registers_existing_file_without_preflight(
    tmp_path, native_library, production_with_shot
):
    path, asset_id, _ = production_with_shot
    with Production.open(path, library_path=native_library) as production:
        original = production.representations[asset_id][0]
        reference = production.host_bindings[RepresentationRef(original.id)]
    proxy = tmp_path / "sh010_proxy.mov"
    proxy.write_bytes(b"proxy media")
    manager = create_manager(
        {"production_path": str(path), "library_path": native_library}
    )
    context = manager.createContext()

    data = TraitsData({LocatableContentTrait.kId, ProxyTrait.kId})
    LocatableContentTrait(data).setLocation(proxy.resolve().as_uri())
    ProxyTrait(data).setLabel("half")
    final = manager.register(
        manager.createEntityReference(reference), data, PublishingAccess.kWrite, context
    )

    with Production.open(path, library_path=native_library) as production:
        binding = production.host_bindings.parse(final.toString())
        assert isinstance(binding.object, RepresentationRef)
        proxy_id = binding.object.id
        assert proxy_id != original.id
        assert production.representation(original.id) == original
        representation = production.representation(proxy_id)
        assert representation.asset_id == asset_id
        assert representation.kind == RepresentationKind.PROXY
        assert production.jobs(limit=10).items[0].state == JobState.SUCCEEDED
    resolved = manager.resolve(final, {ProxyTrait.kId}, ResolveAccess.kRead, context)
    assert ProxyTrait(resolved).getLabel() == "half"


def test_rejects_unsupported_publishing(tmp_path, native_library, production_with_shot):
    path, _, asset_reference = production_with_shot
    manager = create_manager(
        {"production_path": str(path), "library_path": native_library}
    )
    context = manager.createContext()
    asset_entity = manager.createEntityReference(asset_reference)

    def preflight_error(hints, access):
        with pytest.raises(BatchElementException) as error:
            manager.preflight(asset_entity, hints, access, context)
        return error.value.error.code

    assert (
        preflight_error(sequence_traits(), PublishingAccess.kCreateRelated)
        == BatchElementError.ErrorCode.kEntityAccessError
    )
    assert (
        preflight_error(TraitsData(), PublishingAccess.kWrite)
        == BatchElementError.ErrorCode.kInvalidPreflightHint
    )

    working = manager.preflight(
        asset_entity, sequence_traits(), PublishingAccess.kWrite, context
    )
    for location in (
        "https://example.com/sh010.%7Bframe%7D.exr",
        f"{tmp_path.as_uri()}/sh010.%7Bframe%7D.%7Bview%7D.exr",
    ):
        with pytest.raises(BatchElementException) as error:
            manager.register(
                working, sequence_traits(location), PublishingAccess.kWrite, context
            )
        assert error.value.error.code == BatchElementError.ErrorCode.kInvalidTraitSet
    with Production.open(path, library_path=native_library) as production:
        (job,) = production.jobs(limit=10).items
        assert job.state == JobState.REQUESTED
