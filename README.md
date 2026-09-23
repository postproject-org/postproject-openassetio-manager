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

## Development

Install PostProject's native package and Python wheel, then run:

```sh
python -m pip install -e '.[test]'
pytest
```
