# PostProject OpenAssetIO Manager

An experimental OpenAssetIO Manager backed by a PostProject production. It
accepts PostProject's versioned HTTPS host-object references, maps
representations and resources to OpenAssetIO-MediaCreation traits, and
publishes new media as representations with provenance.

Initialize the Manager with:

```python
manager.initialize({
    "production_path": "/show/production.pproj",
    "library_path": "/opt/postproject/lib/libpostproject.so",
    "root.rushes": "/mnt/show/rushes",
})
```

A representation remains one OpenAssetIO entity, including an image sequence. A sequence is reported with
the traits of OpenAssetIO-MediaCreation's `BitmapImageResourceSequence`
specification: `ImageCollectionTrait`, `FrameRangedTrait`, and a templated
`LocatableContentTrait` location such as `file:///shots/sh010.{frame:04d}.exr`
(percent-encoded) with `isTemplated` set.

## Install a release

Download the PostProject native archive and Python wheel from the matching
[PostProject release](https://github.com/postproject-org/postproject/releases), then
download this Manager wheel from the
[Manager release](https://github.com/postproject-org/postproject-openassetio-manager/releases).
Install both wheels together so dependency resolution does not need a source
checkout:

```sh
python -m pip install postproject-0.4.0a1-py3-none-any.whl \
  postproject_openassetio_manager-0.2.0-py3-none-any.whl
```

Pass the extracted native library as `library_path` when initializing the
Manager.

## Development

Install PostProject's native package and Python wheel, then run:

```sh
python -m pip install -e '.[test]'
pytest
```

## Publishing

The Manager implements OpenAssetIO 1.0 publishing (`preflight` and `register`)
on PostProject's job protocol, so a publish is recorded like any other
production work:

- A write-access `managementPolicy` query manages every trait set containing
  `LocatableContentTrait`. The Manager does not drive trait values: the host
  chooses where it writes.
- `preflight` on an asset or representation reference requests a
  `org.postproject:openassetio-publish` job for a new representation of that
  asset and returns the job's host-object reference as the working reference.
  Representations are never modified in place. `ProxyTrait` or `OriginalTrait`
  select the representation kind; other media is recorded as derived.
- `register` on the working reference claims and completes that job in one
  PostProject transaction: the representation, its resources and locator, the
  registered traits, the producing activity (attributed to the host's display
  name), and the job's success become durable together with one revision, or
  not at all. `register` without `preflight` requests the job in the same
  transaction. The final reference names the new representation.
- A non-templated `file://` location becomes a single-file representation. A
  templated location with a `{frame}` or `{frame:0Nd}` variable and
  `FrameRangedTrait` becomes one image-sequence representation; absent frames
  are recorded as missing, and a `framesPerSecond` in the 1000/1001 family is
  stored as an exact rational rate.
- The registered trait set is stored as metadata
  `https://postproject.org/ns/openassetio/1` `traits`, and every other trait
  property under its trait ID and property key, verbatim. Location and frame
  structure are answered from the production, so a relinked sequence resolves to
  its new location.

The working reference names a *requested* job rather than a claimed one:
OpenAssetIO may hand a working reference to another process, and a PostProject
claim token is a capability that must not travel inside an entity reference.
An abandoned preflight leaves a requested job that any PostProject surface can
cancel. Publishing with `kCreateRelated`, to non-file locations, or with
template variables other than `frame` is rejected. Published media has no
recorded inputs, because OpenAssetIO carries no source information for a
publish.

Any PostProject consumer can observe a publish without polling, for example
with a revision waiter on the same production from another process.
