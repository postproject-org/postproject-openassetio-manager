"""Resolve Blender's render from the cross-host shared production."""

import sys
from pathlib import Path

from openassetio.access import ResolveAccess
from openassetio.hostApi import HostInterface, ManagerFactory
from openassetio.log import ConsoleLogger
from openassetio.pluginSystem import PythonPluginSystemManagerImplementationFactory
from openassetio_mediacreation.traits.content import LocatableContentTrait_v1
from postproject import Production, RepresentationKind


class SharedProductionHost(HostInterface):
    """Minimal host identity for the scenario's normal Manager path."""

    def identifier(self):
        return "org.postproject.shared-production"

    def displayName(self):
        return "PostProject shared-production scenario"


production_path = Path(sys.argv[1]).resolve()
library_path = Path(sys.argv[2]).resolve()

with Production.open(production_path, library_path=library_path) as production:
    render = next(
        representation
        for asset in production.assets
        for representation in production.representations[asset.id]
        if representation.kind is RepresentationKind.DERIVED
    )
    reference = production.host_bindings[render.id]

logger = ConsoleLogger()
factory = PythonPluginSystemManagerImplementationFactory(logger)
manager = ManagerFactory.createManagerForInterface(
    "org.postproject.manager", SharedProductionHost(), factory, logger
)
manager.initialize(
    {"production_path": str(production_path), "library_path": str(library_path)}
)
context = manager.createContext()
data = manager.resolve(
    manager.createEntityReference(reference),
    {LocatableContentTrait_v1.kId},
    ResolveAccess.kRead,
    context,
)
location = LocatableContentTrait_v1(data).getLocation()
assert location == (production_path.parent / "blender-render.png").as_uri()
