# PostProject OpenAssetIO Manager

An experimental, read-only OpenAssetIO Manager backed by a PostProject
production. It accepts PostProject's versioned HTTPS host-object references and
maps representations and resources to OpenAssetIO-MediaCreation traits.

Initialize the Manager with:

```python
manager.initialize({
    "production_path": "/show/production.pproj",
    "library_path": "/opt/postproject/lib/libpostproject.so",
    "root.rushes": "/mnt/show/rushes",
})
```

The Manager is intentionally read-only. A representation remains one
OpenAssetIO entity, including an image sequence; its compact frame structure is
reported with `ImageTrait` and `FrameRangedTrait`, while `LocatableContentTrait`
points to the resolved sequence directory.

## Install a release

Download the PostProject native archive and Python wheel from the matching
[PostProject release](https://github.com/postproject-org/postproject/releases), then
download this Manager wheel from the
[Manager release](https://github.com/postproject-org/postproject-openassetio-manager/releases).
Install both wheels together so dependency resolution does not need a source
checkout:

```sh
python -m pip install postproject-0.3.0a1-py3-none-any.whl \
  postproject_openassetio_manager-0.1.0-py3-none-any.whl
```

Pass the extracted native library as `library_path` when initializing the
Manager.

## Development

Install PostProject's native package and Python wheel, then run:

```sh
python -m pip install -e '.[test]'
pytest
```
