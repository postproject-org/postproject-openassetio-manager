"""License-independent configuration, portable reference and sequence checks."""

import json
import shutil
import tomllib
from pathlib import Path

import pytest
from openassetio.access import ResolveAccess
from openassetio.errors import BatchElementException
from openassetio.hostApi import ManagerFactory
from openassetio.log import ConsoleLogger
from openassetio.pluginSystem import PythonPluginSystemManagerImplementationFactory
from postproject import Production
from test_manager import FixtureHost

from postproject_openassetio.traits import FrameRangedTrait, LocatableContentTrait
from tools.nuke_fixture import create_fixture


def manager(config):
    logger = ConsoleLogger()
    return ManagerFactory.defaultManagerForInterface(
        str(config),
        FixtureHost(),
        PythonPluginSystemManagerImplementationFactory(logger),
        logger,
    )


def resolve(manifest, name):
    host = manager(manifest["configs"][name])
    return host.resolve(
        host.createEntityReference(manifest["reference"]),
        {LocatableContentTrait.kId, FrameRangedTrait.kId},
        ResolveAccess.kRead,
        host.createContext(),
    )


def test_generated_config_sequence_and_reference_survive_reopen(
    tmp_path, native_library
):
    path = create_fixture(tmp_path / "fixture ü with spaces", native_library)
    manifest = json.loads(path.read_text())
    config = tomllib.loads(Path(manifest["configs"]["normal"]).read_text())
    assert config["manager"]["identifier"] == "org.postproject.manager"
    assert config["manager"]["settings"]["root.plates"] == manifest["original"]
    with Production.open(
        manifest["production"], library_path=native_library
    ) as production:
        binding = production.host_bindings.parse(manifest["reference"])
        assert str(binding.production_id) == manifest["production_id"]
        representation = production.representation(binding.object.id)
        assert representation.image_sequence.start == 1001
        assert representation.image_sequence.end == 1003
    data = resolve(manifest, "normal")
    assert (
        LocatableContentTrait(data)
        .getLocation()
        .endswith("plate.%7Bframe%3A04d%7D.png")
    )
    assert LocatableContentTrait(data).getIsTemplated() is True
    assert FrameRangedTrait(data).getStartFrame() == 1001
    assert FrameRangedTrait(data).getEndFrame() == 1003
    assert FrameRangedTrait(data).getFramesPerSecond() == 24
    with pytest.raises(FileExistsError):
        create_fixture(path.parent, native_library)


def test_relocated_missing_and_ambiguous_roots_never_pick_a_candidate(
    tmp_path, native_library
):
    manifest = json.loads(
        create_fixture(tmp_path / "fixture", native_library).read_text()
    )
    original = Path(manifest["original"])
    relocated = Path(manifest["relocated"])
    original.rename(relocated)
    data = resolve(manifest, "relocated")
    assert LocatableContentTrait(data).getLocation().startswith(relocated.as_uri())
    shutil.copytree(relocated, manifest["duplicate"])
    with pytest.raises(BatchElementException):
        resolve(manifest, "ambiguous")
    with pytest.raises(BatchElementException):
        resolve(manifest, "missing")
