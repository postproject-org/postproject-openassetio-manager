"""Read-only OpenAssetIO Manager backed by PostProject's public Python API."""

from pathlib import Path

from openassetio import constants
from openassetio.access import EntityTraitsAccess, PolicyAccess, ResolveAccess
from openassetio.errors import BatchElementError
from openassetio.managerApi import ManagerInterface
from openassetio.trait import TraitsData
from openassetio_mediacreation.traits.content import LocatableContentTrait_v1
from openassetio_mediacreation.traits.identity import DisplayNameTrait_v1
from openassetio_mediacreation.traits.managementPolicy import ManagedTrait
from openassetio_mediacreation.traits.timeDomain import FrameRangedTrait_v1
from openassetio_mediacreation.traits.twoDimensional import ImageTrait_v1
from openassetio_mediacreation.traits.usage import EntityTrait_v1
from postproject import (
    AssetId,
    Production,
    RepresentationId,
    ResourceId,
)

REFERENCE_PREFIX = "https://postproject.org/ref/v1/"
LocatableContentTrait = LocatableContentTrait_v1
DisplayNameTrait = DisplayNameTrait_v1
FrameRangedTrait = FrameRangedTrait_v1
ImageTrait = ImageTrait_v1
EntityTrait = EntityTrait_v1


class PostProjectManagerInterface(ManagerInterface):
    """Resolve PostProject host bindings through OpenAssetIO."""

    def __init__(self):
        super().__init__()
        self._production = None
        self._root_mappings = {}
        self._assets = {}
        self._representations = {}
        self._resources = {}

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
        self._index_production()

    def hasCapability(self, capability):
        return capability in (
            ManagerInterface.Capability.kEntityReferenceIdentification,
            ManagerInterface.Capability.kManagementPolicyQueries,
            ManagerInterface.Capability.kResolution,
            ManagerInterface.Capability.kEntityTraitIntrospection,
            ManagerInterface.Capability.kExistenceQueries,
        )

    def managementPolicy(self, traitSets, policyAccess, context, hostSession):
        results = []
        for requested in traitSets:
            result = TraitsData()
            if policyAccess == PolicyAccess.kRead:
                ManagedTrait.imbueTo(result)
                for trait_id in self._resolvable_traits() & set(requested):
                    result.addTrait(trait_id)
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
            except (KeyError, ValueError):
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
        if entityTraitsAccess != EntityTraitsAccess.kRead:
            self._reject_batch(entityReferences, errorCallback, "Entities are read-only")
            return
        for index, reference in enumerate(entityReferences):
            try:
                target = self._lookup(reference.toString())
                successCallback(index, self._traits_for(target))
            except (KeyError, ValueError) as error:
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
            except (KeyError, ValueError) as error:
                errorCallback(index, self._resolution_error(reference, error))

    def _index_production(self):
        self._assets.clear()
        self._representations.clear()
        self._resources.clear()
        for asset in self._production.assets:
            self._assets[str(asset.id)] = asset
            for representation in self._production.representations[asset.id]:
                self._representations[str(representation.id)] = representation
                for resource in representation.resources:
                    self._resources[str(resource.id)] = (representation, resource)

    def _lookup(self, reference):
        binding = self._production.host_bindings.parse(reference)
        if binding.production_id != self._production.id:
            raise ValueError("entity belongs to another production")
        target = binding.object
        if isinstance(target, AssetId):
            return self._assets[str(target)]
        if isinstance(target, RepresentationId):
            return self._representations[str(target)]
        if isinstance(target, ResourceId):
            return self._resources[str(target)]
        raise ValueError("object kind is not exposed as an OpenAssetIO media entity")

    @staticmethod
    def _resolvable_traits():
        return {
            EntityTrait.kId,
            DisplayNameTrait.kId,
            LocatableContentTrait.kId,
            ImageTrait.kId,
            FrameRangedTrait.kId,
        }

    def _traits_for(self, target):
        traits = {EntityTrait.kId}
        if hasattr(target, "display_name") and target.display_name:
            traits.add(DisplayNameTrait.kId)
        representation = target[0] if isinstance(target, tuple) else target
        if hasattr(representation, "resources"):
            traits.add(LocatableContentTrait.kId)
            if representation.image_sequence is not None:
                traits.update({ImageTrait.kId, FrameRangedTrait.kId})
        return traits

    def _data_for(self, target, requested):
        data = TraitsData()
        if DisplayNameTrait.kId in requested and hasattr(target, "display_name"):
            if target.display_name:
                DisplayNameTrait(data).setName(target.display_name)
        representation = target[0] if isinstance(target, tuple) else target
        if hasattr(representation, "resources"):
            if LocatableContentTrait.kId in requested:
                LocatableContentTrait(data).setLocation(self._location_for(representation, target))
            sequence = representation.image_sequence
            if sequence is not None:
                if ImageTrait.kId in requested:
                    ImageTrait.imbueTo(data)
                if FrameRangedTrait.kId in requested:
                    trait = FrameRangedTrait(data)
                    trait.setStartFrame(sequence.start)
                    trait.setEndFrame(sequence.end)
                    trait.setStep(sequence.step)
                    trait.setFramesPerSecond(
                        sequence.rate_numerator / sequence.rate_denominator
                    )
        return data

    def _location_for(self, representation, target):
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
        return resource.candidates[0].uri

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
