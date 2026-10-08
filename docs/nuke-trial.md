# Nuke Read trial

Prepared target: licensed **Nuke 17.0v1**, CPython **3.11** ABI,
OpenAssetIO **1.0.0**, MediaCreation **1.0.0-alpha.12**. The library pins follow
[17.0v1 release notes](https://learn.foundry.com/nuke/content/release_notes/17.0/nuke_17.0v1_releasenotes.html).
Its Python guide still lists older bundled versions; the runtime script checks
the host/build and OpenAssetIO version and records available distribution data.

Local preparation passed with SDK candidate `5eb7545` (Python 0.7.0a1,
C ABI 51, schema 22), Manager development 0.4.0, Python 3.11.15 and both
OpenAssetIO/MediaCreation combinations 1.0.0/alpha.12 and 1.0.2/alpha.13.
These are Manager tests, not Nuke execution. No Nuke binary was found in the
inspected standard locations; licensed runtime acceptance is **not executed**.

The slice is one Read node retaining a canonical PostProject entity reference.
It checks explicit frame bounds, save/reopen, relocation, missing/ambiguous
content, and a deassetized copy that reads with the Manager cleared. It does not
qualify Write publishing, colorspace mapping or interactive use.

## Prepare an isolated fixture

Install the matching SDK/Manager wheels into Nuke's Python environment with
`--no-deps`, retaining its bundled OpenAssetIO packages. The SDK uses ctypes;
the extracted native library must match the wheel's ABI. A normal Python 3.11
environment can generate the fixture:

```sh
python tools/nuke_fixture.py /tmp/postproject-nuke-fixture \
  --library /opt/postproject/lib/libpostproject.so
```

The destination must be new. It contains three real 16×16 RGB PNG frames,
one compact sequence/production, its canonical reference and four TOML configs.
`root.plates` is a local directory mapping; it is not stored in the production.
[The configuration example](../examples/nuke-manager.toml) shows the settings.

The Manager emits the specified MediaCreation `{frame:04d}` template with
`isTemplated=true`. Foundry's [ingest guide](https://learn.foundry.com/nuke/developers/17.0/pythondevguide/openassetio.html)
documents native file tokens such as `####`. Their actual interaction remains
a host acceptance check: the script fails if the OpenAssetIO template survives
unevaluated or the PNG cannot be loaded. It does not advertise a different
template dialect as the standard trait.

## Run with an existing license

Ensure the Manager plugin is discoverable through its installed entry point;
for a source installation, set `OPENASSETIO_PLUGIN_PATH` to this repository's
`src` directory. Give Nuke the matching SDK/Manager Python packages and native
library through the generated configuration.

```sh
export POSTPROJECT_NUKE_FIXTURE=/tmp/postproject-nuke-fixture/fixture.json
export POSTPROJECT_NUKE_OUTPUT=/tmp/postproject-nuke-result
/opt/Nuke17.0v1/Nuke17.0 -t tools/nuke_acceptance.py
```

Output must be new. A passing run writes `acceptance.json`, `managed.nk` and
`render-copy.nk`. Preserve the report and process log. The script restores its
fixture media after relocation tests. It uses the experimental documented
`_asset` API; version changes require another qualification run.

For plugin-free delivery, use the **copy** produced by
[Nuke deassetization](https://learn.foundry.com/nuke/developers/17.0/pythondevguide/_autosummary/nuke.deassetize.html).
Keep the canonical managed comp and its production separately. The copy embeds
local paths; transfer the resolved media and adjust those paths for the render
machine. Missing or ambiguous media must be resolved explicitly before export.

License-independent checks run with `pytest -W error`; they validate actual
Manager discovery/configuration, sequence traits, persisted references and root
resolution. PNG generation follows [W3C PNG](https://www.w3.org/TR/png/).
