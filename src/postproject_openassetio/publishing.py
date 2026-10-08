"""Translate OpenAssetIO publishing trait data into PostProject values.

Nothing here touches a production. The Manager stages the translated values in
one PostProject transaction.
"""

import math
import os
import re
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from openassetio.errors import BatchElementError
from openassetio_mediacreation.traits.content import LocatableContentTrait_v1
from openassetio_mediacreation.traits.representation import (
    OriginalTrait_v1,
    ProxyTrait_v1,
)
from openassetio_mediacreation.traits.timeDomain import FrameRangedTrait_v1
from postproject import (
    FileSource,
    ImageSequenceSource,
    MetadataBool,
    MetadataDecimal,
    MetadataI64,
    MetadataList,
    MetadataProperty,
    MetadataString,
    RepresentationKind,
    SequenceNaming,
)

LocatableContentTrait = LocatableContentTrait_v1
FrameRangedTrait = FrameRangedTrait_v1

PUBLISH_KIND = "org.postproject:openassetio-publish"
"""Job and activity kind of every publish through this Manager."""

MANAGER_VOCABULARY = "https://postproject.org/ns/openassetio/1"
TRAIT_SET_PROPERTY = MetadataProperty(MANAGER_VOCABULARY, "traits")
"""The registered trait set, which OpenAssetIO requires a manager to persist."""

STRUCTURAL_PROPERTIES = frozenset(
    {
        (LocatableContentTrait.kId, "location"),
        (LocatableContentTrait.kId, "isTemplated"),
        (FrameRangedTrait.kId, "startFrame"),
        (FrameRangedTrait.kId, "endFrame"),
        (FrameRangedTrait.kId, "step"),
        (FrameRangedTrait.kId, "framesPerSecond"),
    }
)
"""Trait properties PostProject records as representation structure.

They are answered from the production's current knowledge, so a relinked
sequence reports its new location rather than the registered one.
"""

_FRAME_TOKEN = re.compile(
    r"(?P<prefix>[^{}]*)\{frame(?::0(?P<padding>[1-9]\d?)d)?\}(?P<suffix>[^{}]*)"
)


class PublishError(Exception):
    """A publishing request that fails with a specific OpenAssetIO error code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

    def batch_error(self):
        return BatchElementError(self.code, str(self))


def invalid_trait_set(message):
    return PublishError(BatchElementError.ErrorCode.kInvalidTraitSet, message)


def representation_kind(traits_data):
    """Map MediaCreation representation traits to a PostProject kind.

    Published media without an ``Original`` or ``Proxy`` trait is generated
    material, which PostProject records as a derived representation.
    """

    if traits_data.hasTrait(ProxyTrait_v1.kId):
        return RepresentationKind.PROXY
    if traits_data.hasTrait(OriginalTrait_v1.kId):
        return RepresentationKind.ORIGINAL
    return RepresentationKind.DERIVED


def content_from_traits(traits_data):
    """Return the media source a registered trait set locates."""

    if not traits_data.hasTrait(LocatableContentTrait.kId):
        raise invalid_trait_set("published media needs LocatableContentTrait")
    content = LocatableContentTrait(traits_data)
    location = content.getLocation()
    if not location:
        raise invalid_trait_set("LocatableContentTrait has no location")
    path = _file_path(location)
    if not content.getIsTemplated(False):
        return FileSource(Path(path))
    directory, name = os.path.split(path)
    match = _FRAME_TOKEN.fullmatch(name)
    if match is None:
        raise invalid_trait_set(
            "a templated location must name frames with {frame} or {frame:0Nd} "
            "and no other variable"
        )
    return _sequence(traits_data, directory, match)


def frame_rate(frames_per_second):
    """Return an exact rate, recognizing the 1000/1001 NTSC family."""

    if not math.isfinite(frames_per_second) or frames_per_second <= 0:
        raise invalid_trait_set("framesPerSecond must be a positive number")
    for denominator in (1, 1001):
        numerator = round(frames_per_second * denominator)
        if abs(numerator / denominator - frames_per_second) < 1e-3:
            return Fraction(numerator, denominator)
    rate = Fraction(frames_per_second).limit_denominator(1001)
    return rate


def persisted_metadata(traits_data):
    """Yield the trait set and every non-structural property as metadata.

    Trait IDs and property keys are OpenAssetIO's own identifiers and are stored
    verbatim as the vocabulary and property of each assertion.
    """

    trait_ids = sorted(traits_data.traitSet())
    yield (
        TRAIT_SET_PROPERTY,
        MetadataList(tuple(MetadataString(item) for item in trait_ids)),
    )
    for trait_id in trait_ids:
        for key in sorted(traits_data.traitPropertyKeys(trait_id)):
            if (trait_id, key) in STRUCTURAL_PROPERTIES:
                continue
            value = traits_data.getTraitProperty(trait_id, key)
            yield MetadataProperty(trait_id, key), metadata_value(value)


def metadata_value(value):
    """Convert one OpenAssetIO property value to a typed metadata value."""

    if isinstance(value, bool):
        return MetadataBool(value)
    if isinstance(value, int):
        return MetadataI64(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise invalid_trait_set("trait properties must be finite numbers")
        sign, digits, exponent = Decimal(repr(value)).as_tuple()
        coefficient = int("".join(map(str, digits))) * (-1 if sign else 1)
        if exponent >= 0:
            return MetadataDecimal(coefficient * 10**exponent, 0)
        return MetadataDecimal(coefficient, -exponent)
    if isinstance(value, str):
        return MetadataString(value)
    raise invalid_trait_set(f"unsupported trait property value: {value!r}")


def property_value(value):
    """Convert persisted metadata back to an OpenAssetIO property value."""

    if isinstance(value, MetadataBool | MetadataI64 | MetadataString):
        return value.value
    if isinstance(value, MetadataDecimal):
        return float(Decimal(value.coefficient).scaleb(-value.scale))
    return None


def trait_set(value):
    """Return the persisted trait set of a ``TRAIT_SET_PROPERTY`` value."""

    if not isinstance(value, MetadataList):
        return set()
    return {item.value for item in value.values if isinstance(item, MetadataString)}


def _file_path(location):
    parts = urlsplit(location)
    if parts.scheme != "file" or parts.netloc not in ("", "localhost"):
        raise invalid_trait_set("only local file:// locations can be published")
    return url2pathname(parts.path) if os.name == "nt" else unquote(parts.path)


def _sequence(traits_data, directory, match):
    if not traits_data.hasTrait(FrameRangedTrait.kId):
        raise invalid_trait_set("a templated location needs FrameRangedTrait")
    frames = FrameRangedTrait(traits_data)
    start = frames.getStartFrame()
    end = frames.getEndFrame()
    frames_per_second = frames.getFramesPerSecond()
    step = frames.getStep(1)
    if start is None or end is None or frames_per_second is None:
        raise invalid_trait_set(
            "FrameRangedTrait needs startFrame, endFrame, and framesPerSecond"
        )
    if end < start or step < 1:
        raise invalid_trait_set("the frame range is empty")
    prefix = match["prefix"]
    suffix = match["suffix"]
    padding = int(match["padding"] or 0)
    missing = tuple(
        frame
        for frame in range(start, end + 1, step)
        if not os.path.isfile(
            os.path.join(directory, f"{prefix}{frame:0{padding}d}{suffix}")
        )
    )
    rate = frame_rate(frames_per_second)
    return ImageSequenceSource(
        directory,
        SequenceNaming(prefix, suffix, padding),
        start,
        end,
        step,
        rate,
        missing,
    )
