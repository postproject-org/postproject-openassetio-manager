"""OpenAssetIO Manager backed by PostProject's public Python API."""

import time
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import quote

from openassetio import EntityReference, constants
from openassetio.access import (
    EntityTraitsAccess,
    PolicyAccess,
    PublishingAccess,
    ResolveAccess,
)
from openassetio.errors import BatchElementError
from openassetio.managerApi import ManagerInterface
from openassetio.trait import TraitsData
from openassetio_mediacreation.traits.content import LocatableContentTrait_v1
from openassetio_mediacreation.traits.identity import DisplayNameTrait_v1
from openassetio_mediacreation.traits.managementPolicy import ManagedTrait
from openassetio_mediacreation.traits.timeDomain import FrameRangedTrait_v1
from openassetio_mediacreation.traits.twoDimensional import ImageCollectionTrait_v1
from openassetio_mediacreation.traits.usage import EntityTrait_v1
from postproject import (
    ActivityEdge,
    ActivitySpec,
    AssetRef,
    JobRef,
    JobRequest,
    JobState,
    OriginIdentity,
    PostProjectError,
    Production,
    RepresentationRef,
    ResourceRef,
    RevisionContext,
    ToolIdentity,
)

from .publishing import (
    MANAGER_VOCABULARY,
    PUBLISH_KIND,
    STRUCTURAL_PROPERTIES,
    TRAIT_SET_PROPERTY,
    PublishError,
    content_from_traits,
    persisted_metadata,
    property_value,
    representation_kind,
    trait_set,
)

REFERENCE_PREFIX = "https://postproject.org/ref/v1/"
LocatableContentTrait = LocatableContentTrait_v1
DisplayNameTrait = DisplayNameTrait_v1
FrameRangedTrait = FrameRangedTrait_v1
ImageCollectionTrait = ImageCollectionTrait_v1
EntityTrait = EntityTrait_v1

CLAIM_LEASE_MICROS = 60_000_000
"""Lease of the claim that registration takes and completes in one commit."""

REPOSITORY_URI = "https://github.com/postproject-org/postproject-openassetio-manager"


class PostProjectManagerInterface(ManagerInterface):
    """Resolve and publish PostProject media through OpenAssetIO."""

    def __init__(self):
        super().__init__()
        self._production = None
        self._root_mappings = {}

    def identifier(self):
        return "org.postproject.manager"

    def displayName(self):
        return "PostProject"

    def info(self):
        return {constants.kInfoKey_EntityReferencesMatchPrefix: REFERENCE_PREFIX}

    def settings(self, hostSession):
        return {
            "production_path": "",
            "library_path": "",
        }

    def initialize(self, managerSettings, hostSession):
        production_path = managerSettings.get("production_path")
        if not production_path:
            raise KeyError("production_path is required")
        library_path = managerSettings.get("library_path") or None
        self._production = Production.open(production_path, library_path=library_path)
        self._root_mappings = {
            key.removeprefix("root."): value
            for key, value in managerSettings.items()
            if key.startswith("root.")
        }

    def hasCapability(self, capability):
        return capability in (
            ManagerInterface.Capability.kEntityReferenceIdentification,
            ManagerInterface.Capability.kManagementPolicyQueries,
            ManagerInterface.Capability.kResolution,
            ManagerInterface.Capability.kEntityTraitIntrospection,
            ManagerInterface.Capability.kExistenceQueries,
            ManagerInterface.Capability.kPublishing,
        )

    def managementPolicy(self, traitSets, policyAccess, context, hostSession):
        results = []
        for requested in traitSets:
            result = TraitsData()
            if policyAccess == PolicyAccess.kRead:
                ManagedTrait.imbueTo(result)
                for trait_id in self._resolvable_traits() & set(requested):
                    result.addTrait(trait_id)
            elif policyAccess == PolicyAccess.kWrite and LocatableContentTrait.kId in requested:
                # Registration persists every trait and property verbatim.
                ManagedTrait.imbueTo(result)
                result.addTraits(set(requested))
            results.append(result)
        return results

    def isEntityReferenceString(self, someString, hostSession):
        return someString.startswith(REFERENCE_PREFIX)

    def entityExists(
        self, entityReferences, context, hostSession, successCallback, errorCallback
    ):
        for index, reference in enumerate(entityReferences):
            try:
                self._lookup(reference.toString())
                successCallback(index, True)
            except (PostProjectError, ValueError):
                successCallback(index, False)

    def entityTraits(
        self,
        entityReferences,
        entityTraitsAccess,
        context,
        hostSession,
        successCallback,
        errorCallback,
    ):
        if entityTraitsAccess == EntityTraitsAccess.kWrite:
            for index, reference in enumerate(entityReferences):
                try:
                    self._publish_target(reference.toString())
                    successCallback(index, {LocatableContentTrait.kId})
                except PublishError as error:
                    errorCallback(index, error.batch_error())
            return
        for index, reference in enumerate(entityReferences):
            try:
                target = self._lookup(reference.toString())
                successCallback(index, self._traits_for(target))
            except (PostProjectError, ValueError) as error:
                errorCallback(index, self._resolution_error(reference, error))

    def resolve(
        self,
        entityReferences,
        traitSet,
        resolveAccess,
        context,
        hostSession,
        successCallback,
        errorCallback,
    ):
        if resolveAccess != ResolveAccess.kRead:
            self._reject_batch(entityReferences, errorCallback, "Entities are read-only")
            return
        for index, reference in enumerate(entityReferences):
            try:
                target = self._lookup(reference.toString())
                successCallback(index, self._data_for(target, set(traitSet)))
            except (PostProjectError, ValueError) as error:
                errorCallback(index, self._resolution_error(reference, error))

    def preflight(
        self,
        entityReferences,
        traitsHints,
        publishingAccess,
        context,
        hostSession,
        successCallback,
        errorCallback,
    ):
        for index, (reference, hints) in enumerate(zip(entityReferences, traitsHints)):
            try:
                self._require_write(publishingAccess)
                target = self._publish_target(reference.toString())
                if isinstance(target, JobRef):
                    # Preflighting a working reference again keeps it.
                    successCallback(index, reference)
                    continue
                if not hints.hasTrait(LocatableContentTrait.kId):
                    raise PublishError(
                        BatchElementError.ErrorCode.kInvalidPreflightHint,
                        "published media needs LocatableContentTrait",
                    )
                request = JobRequest(PUBLISH_KIND, (), target.id, representation_kind(hints))
                with self._production.transaction() as transaction:
                    transaction.set_revision_context(
                        self._revision_context(f"Prepare publish to {reference.toString()}")
                    )
                    job_id = transaction.request_job(request)
                successCallback(index, EntityReference(self._production.host_bindings[JobRef(job_id)]))
            except PublishError as error:
                errorCallback(index, error.batch_error())

    def register(
        self,
        entityReferences,
        entityTraitsDatas,
        publishingAccess,
        context,
        hostSession,
        successCallback,
        errorCallback,
    ):
        for index, (reference, data) in enumerate(zip(entityReferences, entityTraitsDatas)):
            try:
                self._require_write(publishingAccess)
                target = self._publish_target(reference.toString())
                representation_id = self._register(target, data, hostSession)
                successCallback(
                    index, EntityReference(self._production.host_bindings[RepresentationRef(representation_id)])
                )
            except PublishError as error:
                errorCallback(index, error.batch_error())
            except PostProjectError as error:
                errorCallback(
                    index,
                    BatchElementError(
                        BatchElementError.ErrorCode.kEntityAccessError,
                        f"Entity '{reference.toString()}' cannot be registered: {error}",
                    ),
                )

    def _register(self, target, data, hostSession):
        content = content_from_traits(data)
        if isinstance(target, JobRef):
            job = self._production.job(target.id)
            job_id, asset_id, kind = job.id, job.output_asset_id, job.output_representation_kind
        else:
            job_id, asset_id, kind = None, target.id, representation_kind(data)
        tool = ToolIdentity(hostSession.host().displayName())
        now = time.time_ns() // 1_000
        # The request (without preflight), claim, representation, persisted
        # traits, activity, and completion become durable together or not at all.
        with self._production.transaction() as transaction:
            transaction.set_revision_context(self._revision_context("Register published media"))
            if job_id is None:
                job_id = transaction.request_job(JobRequest(PUBLISH_KIND, (), asset_id, kind))
            claim_id = transaction.claim_job(job_id, tool, None, now, now + CLAIM_LEASE_MICROS)
            representation_id = transaction.add_representation(asset_id, kind, content)
            for metadata_property, value in persisted_metadata(data):
                transaction.add_metadata(RepresentationRef(representation_id), metadata_property, value)
            activity_id = transaction.create_activity(
                ActivitySpec(
                    PUBLISH_KIND,
                    (ActivityEdge(representation_id),),
                    finished_at_unix_micros=now,
                    tool=tool,
                )
            )
            transaction.complete_job(job_id, claim_id, now, representation_id, activity_id)
        return representation_id

    def _publish_target(self, reference):
        """Return the asset a new representation joins, or an open working job."""

        try:
            target = self._parse(reference)
            if isinstance(target, AssetRef):
                return AssetRef(self._production.asset(target.id).id)
            if isinstance(target, RepresentationRef):
                # Representations are immutable facts: writing to one adds a
                # new representation of its asset and leaves it untouched.
                return AssetRef(self._production.representation(target.id).asset_id)
            if isinstance(target, JobRef):
                job = self._production.job(target.id)
                if job.kind == PUBLISH_KIND and job.state == JobState.REQUESTED:
                    return JobRef(job.id)
        except (PostProjectError, ValueError) as error:
            raise PublishError(
                BatchElementError.ErrorCode.kEntityAccessError,
                f"Entity '{reference}' cannot be published to: {error}",
            ) from error
        raise PublishError(
            BatchElementError.ErrorCode.kEntityAccessError,
            f"Entity '{reference}' is not an asset, representation, or open working reference",
        )

    @staticmethod
    def _require_write(publishingAccess):
        if publishingAccess != PublishingAccess.kWrite:
            raise PublishError(
                BatchElementError.ErrorCode.kEntityAccessError,
                "Creating related entities is not supported",
            )

    @staticmethod
    def _revision_context(message):
        try:
            manager_version = version("postproject-openassetio-manager")
        except PackageNotFoundError:
            manager_version = None
        origin = OriginIdentity("PostProject OpenAssetIO Manager", manager_version, REPOSITORY_URI)
        return RevisionContext(origin, message)

    def _lookup(self, reference):
        # Entities are read by identity on every call, so media committed by
        # other processes after initialization is visible without re-indexing.
        target = self._parse(reference)
        if isinstance(target, AssetRef):
            return self._production.asset(target.id)
        if isinstance(target, RepresentationRef):
            return self._production.representation(target.id)
        if isinstance(target, ResourceRef):
            users = self._production.representations_using_resource(target.id, limit=2)
            if len(users.items) != 1:
                raise ValueError("resource is not used by exactly one representation")
            representation = users.items[0]
            resource = next(item for item in representation.resources if item.id == target.id)
            return representation, resource
        raise ValueError("object kind is not exposed as an OpenAssetIO media entity")

    def _parse(self, reference):
        binding = self._production.host_bindings.parse(reference)
        if binding.production_id != self._production.id:
            raise ValueError("entity belongs to another production")
        return binding.object

    @staticmethod
    def _resolvable_traits():
        return {
            EntityTrait.kId,
            DisplayNameTrait.kId,
            LocatableContentTrait.kId,
            ImageCollectionTrait.kId,
            FrameRangedTrait.kId,
        }

    def _persisted(self, target):
        """Return registered trait properties as ``{trait: {key: value}}``."""

        representation = target[0] if isinstance(target, tuple) else target
        if not hasattr(representation, "resources"):
            return {}
        persisted = {}
        for assertion in self._production.metadata[RepresentationRef(representation.id)]:
            vocabulary = assertion.property.vocabulary
            if assertion.property == TRAIT_SET_PROPERTY:
                for trait_id in trait_set(assertion.value):
                    persisted.setdefault(trait_id, {})
            elif vocabulary != MANAGER_VOCABULARY:
                value = property_value(assertion.value)
                if value is not None:
                    persisted.setdefault(vocabulary, {})[assertion.property.property] = value
        return persisted

    def _traits_for(self, target):
        traits = {EntityTrait.kId} | set(self._persisted(target))
        if hasattr(target, "display_name") and target.display_name:
            traits.add(DisplayNameTrait.kId)
        representation = target[0] if isinstance(target, tuple) else target
        if hasattr(representation, "resources"):
            traits.add(LocatableContentTrait.kId)
            if representation.image_sequence is not None:
                traits.update({ImageCollectionTrait.kId, FrameRangedTrait.kId})
        return traits

    def _data_for(self, target, requested):
        data = TraitsData()
        for trait_id, properties in self._persisted(target).items():
            if trait_id in requested:
                data.addTrait(trait_id)
                for key, value in properties.items():
                    if (trait_id, key) not in STRUCTURAL_PROPERTIES:
                        data.setTraitProperty(trait_id, key, value)
        if DisplayNameTrait.kId in requested and hasattr(target, "display_name"):
            if target.display_name:
                DisplayNameTrait(data).setName(target.display_name)
        representation = target[0] if isinstance(target, tuple) else target
        if hasattr(representation, "resources"):
            sequence = representation.image_sequence
            if LocatableContentTrait.kId in requested:
                trait = LocatableContentTrait(data)
                candidate = self._candidate_for(representation, target)
                location = candidate.uri
                if sequence is not None:
                    # The file names belong to the resolved location, which
                    # may name the frames differently from another copy.
                    if candidate.sequence_naming is None:
                        raise ValueError("image-sequence location has no file naming")
                    template = frame_template(candidate.sequence_naming)
                    location = f"{location.rstrip('/')}/{quote(template)}"
                trait.setLocation(location)
                trait.setIsTemplated(sequence is not None)
            if sequence is not None:
                if ImageCollectionTrait.kId in requested:
                    ImageCollectionTrait.imbueTo(data)
                if FrameRangedTrait.kId in requested:
                    trait = FrameRangedTrait(data)
                    trait.setStartFrame(sequence.start)
                    trait.setEndFrame(sequence.end)
                    trait.setStep(sequence.step)
                    trait.setFramesPerSecond(
                        sequence.rate_numerator / sequence.rate_denominator
                    )
        return data

    def _candidate_for(self, representation, target):
        resource_id = target[1].id if isinstance(target, tuple) else representation.resources[0].id
        resolutions = self._production.resolve(
            representation.asset_id, self._root_mappings
        )
        resolved = next(
            result for result in resolutions if result.representation_id == representation.id
        )
        resource = next(item for item in resolved.resources if item.resource_id == resource_id)
        if len(resource.candidates) != 1:
            raise ValueError("resource does not resolve to exactly one location")
        return resource.candidates[0]

    @staticmethod
    def _reject_batch(entityReferences, errorCallback, message):
        error = BatchElementError(
            BatchElementError.ErrorCode.kEntityAccessError, message
        )
        for index in range(len(entityReferences)):
            errorCallback(index, error)

    @staticmethod
    def _resolution_error(reference, error):
        return BatchElementError(
            BatchElementError.ErrorCode.kEntityResolutionError,
            f"Entity '{reference.toString()}' cannot be resolved: {error}",
        )


def frame_template(naming):
    """Return a sequence file naming in OpenAssetIO's ``{frame}`` template syntax."""

    token = "{frame}" if naming.padding <= 1 else f"{{frame:0{naming.padding}d}}"
    return f"{naming.prefix}{token}{naming.suffix}"
