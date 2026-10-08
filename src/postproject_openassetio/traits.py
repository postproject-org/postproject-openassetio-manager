"""Version-one MediaCreation classes in alpha.12 and later generated packages.

Nuke's bundled alpha.12 uses unversioned class names. Later releases expose
explicit ``_v1`` names. Select the installed definition without changing IDs or
trait property values.
"""

from openassetio_mediacreation.specifications import twoDimensional as specifications
from openassetio_mediacreation.traits import (
    content,
    identity,
    representation,
    timeDomain,
    twoDimensional,
    usage,
)


def _v1(module, name):
    explicit = getattr(module, name + "_v1", None)
    return explicit if explicit is not None else getattr(module, name)


LocatableContentTrait = _v1(content, "LocatableContentTrait")
DisplayNameTrait = _v1(identity, "DisplayNameTrait")
OriginalTrait = _v1(representation, "OriginalTrait")
ProxyTrait = _v1(representation, "ProxyTrait")
FrameRangedTrait = _v1(timeDomain, "FrameRangedTrait")
ImageCollectionTrait = _v1(twoDimensional, "ImageCollectionTrait")
PixelBasedTrait = _v1(twoDimensional, "PixelBasedTrait")
EntityTrait = _v1(usage, "EntityTrait")
BitmapImageResourceSequenceSpecification = _v1(
    specifications, "BitmapImageResourceSequenceSpecification"
)
