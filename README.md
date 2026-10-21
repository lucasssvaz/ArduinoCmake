# acmake — Arduino CMake builder

Python CLI that resolves an **FQBN**, discovers locally installed **Arduino cores and libraries**, generates **CMake + Ninja** build files from `platform.txt` / `boards.txt` recipes, compiles sketches, and can run **upload** patterns.

## Requirements

- Python 3.10+
- **CMake** 3.20+ and **Ninja** on `PATH`
- Arduino packages in the usual data directory (e.g. `~/Library/Arduino15` on macOS)
- Optional: **`arduino-preprocessor`** on `PATH` (or next to `arduino-cli`) for `.ino` prototype generation

## How to run the program

Use any one of these; the CLI is the same (`compile`, `upload`, `cache-prune`, `cache-clear`, `board`).

| Method | When |
|--------|------|
| `acmake …` | After `pip install -e .` or a normal install; `acmake` is on `PATH`. |
| `python -m acmake …` | Installed package; avoids shadowing by a local `acmake.py`. |
| `python3 acmake.py …` | From this repository root, without installing (prepends `src/` on `sys.path`). |
| `chmod +x acmake.py && ./acmake.py …` | Same as above if the file is executable. |
| `python3 arduino_cmake.py …` | **Portable** single file in the repo root (or copy it anywhere). Extracts the bundled `acmake` package under `~/.cache/arduino_cmake_portable/<id>/` on first use. |
| `./arduino_cmake.py …` | After `chmod +x arduino_cmake.py`. |

To rebuild `arduino_cmake.py` after changing sources under `src/acmake/`:

```bash
python3 tools/gen_arduino_cmake_portable.py
```

### Install (editable, for development)

```bash
pip install -e ".[dev]"
```

## Global options (all subcommands)

These apply before the subcommand name:

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show help for the top-level parser or `acmake <subcommand> -h`. |
| `-v` / `-vv` | Increase verbosity (`-v`: print CMake configure/build commands; `-vv`: more internal detail). |
| `--data-dir DIR` | Arduino **data** directory (Board Manager cores, tools). Default: `ARDUINO_DIRECTORIES_DATA` or OS default (e.g. `~/Library/Arduino15`). |
| `--user-dir DIR` | Sketchbook / **user** directory (sketches, user `hardware/`, `libraries/`). Default: `ARDUINO_DIRECTORIES_USER`, else **`~/Arduino`** on Linux or **`~/Documents/Arduino`** on macOS and Windows. |

## `acmake compile`

Generate CMake in the build directory, run CMake + Ninja, run optional post-build hooks, then print size / library summaries.

| Option | Required | Description |
|--------|----------|-------------|
| `--fqbn` | yes | Board FQBN, e.g. `arduino:avr:uno` or `espressif:esp32:esp32s3:PartitionScheme=default,CPUFreq=240`. **Quote** the whole value in the shell so commas stay in one argument. |
| `--sketch` | yes | Path to the sketch folder (the directory that contains the `.ino` files). |
| `--build-path` | no | Build output directory (same as `arduino-cli --build-path`). Default: `<sketch>/build`. |
| `--output-dir` | no | Alias for `--build-path` when `--build-path` is not set. |
| `--ide-version` | no | Value for `runtime.ide.version` style defines (default: `10607`). |
| `--clean` | no | Delete the build directory before configuring. |
| `--no-preprocessor` | no | Skip `arduino-preprocessor`; concatenates `.ino` files only (may break link if the sketch needs prototypes). |
| `--export-binaries` | no | After a successful build, run `recipe.hooks.savehex.presavehex` / `postsavehex` (same idea as `arduino-cli --export-binaries`). |
| `--no-object-cache` | no | Keep all `.o` files and `core.a` under the sketch build dir instead of the shared temp cache (see below). |
| `--warnings LEVEL` | no | One of `none`, `default`, `more`, `all`: sets ``compiler.warning_flags`` from ``compiler.warning_flags.<LEVEL>`` in ``platform.txt`` (same as arduino-cli ``--warnings``). With the shared object cache on, this selects a separate cache subtree so flags stay consistent. |
| `--build-property KEY=VALUE` | no | Override a merged platform/board property (repeatable; same as arduino-cli ``--build-property``). First ``=`` separates key from value, so values may contain ``=``. Changes the object-cache bucket when the shared cache is on. |

Examples:

```bash
acmake compile --fqbn arduino:avr:uno --sketch /path/to/Blink
acmake compile --fqbn arduino:avr:uno --sketch /path/to/Blink --clean
acmake compile --fqbn arduino:avr:uno --sketch /path/to/Blink --build-path /tmp/mybuild
acmake compile --fqbn arduino:avr:uno --sketch /path/to/Blink --no-preprocessor
acmake compile --fqbn arduino:avr:uno --sketch /path/to/Blink --export-binaries
acmake -v compile --fqbn arduino:avr:uno --sketch /path/to/Blink
acmake compile --fqbn 'espressif:esp32:esp32s3:USBMode=default' --sketch /path/to/MySketch \
  --data-dir ~/Library/Arduino15 --user-dir ~/Documents/Arduino
acmake compile --fqbn espressif:esp32:esp32s3 --sketch /path/to/Sketch \
  --build-property 'compiler.warning_flags.all=-Wall -Werror=all -Wextra'
```

### Shared object cache (default on)

Object files for **core**, **variant**, and **each linked library** are shared under the system temp directory. The cache directory name is **32 hex characters**: SHA-256 (first 32 hex chars) of ``FQBN.to_string()`` + a NUL + the board package **version** string from ``platform.txt`` / expanded properties (so different core package versions never share the same cache tree). The SHA-256 **hex digest of ``build_opt.h`` bytes** in the current sketch ``build/`` directory is also mixed in (same bytes → same subtree, including across different examples; different bytes → a separate subtree). When the platform defines ``compiler.sdk.path`` (e.g. the ESP32 core's ``esp32-arduino-libs``), a ``sdk=…`` digest of that SDK's config inputs — the generated ``sdkconfig`` plus the ``flags/*`` define / include files — is mixed in as well, so regenerating the SDK with a different Kconfig (which does **not** bump the core package version) gets its own subtree instead of reusing ``.o`` files compiled against the old ``sdkconfig``. If you pass ``--warnings <LEVEL>``, a ``warnings=<LEVEL>`` segment is mixed into that hash so cached objects are not reused across different warning levels. If you pass one or more ``--build-property`` flags, a digest of those strings is added as ``props=…`` for the same reason. The **per-sketch build dir** defaults to ``<sketch>/build`` (override with ``--build-path``).

Layout (sketch ``.o`` files stay under the sketch build dir):

- ``<temp>/acmake_objcache/<32-hex-key>/core_generations/<core-generation-sha256>/core/o/…`` and ``…/core/core.a``
- ``…/core_generations/<core-generation-sha256>/variant/o/…``
- ``…/library_generations/<platform-header-config-sha256>/lib/<LibraryName>_<hash>/generations/<library-generation-sha256>/o/…``

**Invalidation never deletes artifacts.** Garbage collection is an explicit ``acmake cache-prune`` operation, so selecting a new immutable generation cannot race another build still using an older one. Core generations include every regular compile-input candidate under core/variant trees (including extensionless, ``.inc``, ``.ipp``, and ``.tcc`` files), normalized effective compile commands, recursively expanded response files, direct file-valued options (``-include``, ``-imacros``, specs, plugins, ``-B`` tool trees, wrappers, and other existing file arguments), platform/board configuration, explicit/environment include roots, output-affecting compiler environment, compiler/archiver identities, and the existing FQBN/build-option/SDK bucket identity. Library traversal exactly follows compiled sources plus effective include roots; normal exclusions are evaluated relative to the library root only and can never hide a compiled ``src/tests`` source or a library merely installed beneath an absolute ``tmp``/``tests`` directory.

Library generations use a separate platform-header/config identity plus that library's normalized command and exactly its transitive dependency/include-root closure. Environment roots such as ``CPATH`` are considered covered only when they fall inside that specific closure, so another globally linked library cannot hide a compiler input. Consequently an unrelated core source or unrelated linked library does not evict reusable library objects.

Digests are memoized within one preparation call. Across CLI invocations, independent root/scope manifest shards use separate locks and reuse SHA-256 results only when device, inode, size, nanosecond mtime, and nanosecond ctime all still match; successful scans prune removed entries. Windows and filesystems without reliable change identity bypass persistent reuse and hash content directly. A changed identity causes a stable content re-read, while touching a file may recompute its digest without selecting a different generation when bytes are unchanged.

Cached object and archive publication is process-safe and immutable. Writers take an advisory lock scoped to the individual artifact, recheck after locking, build a same-directory temporary file, and atomically publish only when the generation path does not yet exist; an existing object/archive is never replaced. Since archive inputs are themselves immutable and encoded by the generation path, a warm ``core.a`` hit needs only an existence check rather than re-hashing every object.

Coverage builds (``--coverage`` or ``-ftest-coverage`` in the effective C/C++ recipes or any recursively referenced response file) do **not** use the shared object cache. Their objects and matching ``.gcno`` files remain together under the sketch build directory and are collected by the existing ``gcov/`` flow.

**CMake** runs the standalone ``cache_compile.py`` and ``cache_archive.py`` wrappers for shared artifacts (no ``acmake`` package needed on ``PYTHONPATH``). Ninja **DEPFILE** is not used for cached compile rules; sketch objects still use ``-MMD`` / DEPFILE under ``<sketch build>/.acmake_deps/``.

- **Clear everything:** ``acmake cache-clear`` removes the entire ``<temp>/acmake_objcache`` directory (all FQBNs / versions). Explicit clearing while builds are active is unsupported; wait for all builds to finish first.
- **Prune old generations:** ``acmake cache-prune`` removes buckets unused for 30 days and old generations beyond the two newest in each active group. Use ``--dry-run`` to inspect the result. Pruning while builds are active is unsupported.
- Disable cache for one build: ``acmake compile … --no-object-cache`` (``upload`` has the same flag).
- Environment: ``ACMAKE_OBJECT_CACHE=0`` (``false``, ``no``, ``off`` also turn it off).
- ``-v`` logs the resolved cache path as ``object cache: …``.

``build_opt.h`` is copied from the sketch only when bytes differ (so mtimes do not churn every run). ``sketch.cpp`` from the preprocessor is written only when output bytes differ. Library discovery and CMake dependency lists use deterministic ordering so ``CMakeLists.txt`` stays stable when nothing real changed. For shared-cached **library** compiles, paths under the sketch ``build_dir`` from recipe ``@…`` stubs (e.g. ``build_opt.h``) are omitted from Ninja ``DEPENDS`` so a brand-new example ``build/`` does not make Ninja re-run every linked library; the compiler argv still includes those files, and content-addressed bucket/generation selection keeps differing inputs separate. Each cached library TU also gets its own ``-I`` list (core + variant + that library + others it pulls in via ``depends=`` or ``#include`` tokens among **already linked** libraries), not the whole sketch link set, so ``WiFi.cpp`` compiles the same across examples that add unrelated libraries. For those same rules, ``-MF`` points at a depfile path **relative to the sketch build dir** (not an absolute path under ``…/OtherSketch/build/``), so Ninja does not treat a new example directory as a different command for the same shared ``.o``. ESP32 also puts ``-I{build.source.path}`` in ``compiler.cpreprocessor.flags``; that flag is **removed** from cached core/variant/lib recipes only (sketch translation units keep it) so the rule text does not embed each example’s ``.ino`` directory path. ``cmake -S … -B …`` runs only until ``CMakeCache.txt`` and ``build.ninja`` exist; later builds use ``cmake --build`` only.

## `acmake cache-clear`

Deletes the whole shared object cache directory (``<temp>/acmake_objcache``). No arguments. Use after toolchain upgrades or if you want a clean slate for all boards. Do not clear the cache while any build is active.

## `acmake cache-prune`

Garbage-collects immutable object-cache generations without coupling deletion to invalidation. By default, a whole FQBN/build-option/SDK bucket is removed after 30 days without use. Within active buckets, expired core, library-platform, and individual-library generations are removed while the two newest entries in each group are retained.

| Option | Default | Description |
|--------|---------|-------------|
| `--max-age-days DAYS` | `30` | Expiration age. Cache use is recorded at most once per day. |
| `--keep N` | `2` | Minimum recent generations retained in each active generation group. |
| `--dry-run` | off | Report eligible directories and bytes without deleting them. |

As with `cache-clear`, do not prune while builds are active.

## `acmake upload`

Resolves the same FQBN/sketch/build layout as `compile`, then runs the platform’s `upload.tool` recipe (e.g. `esptool`, `avrdude`).

| Option | Required | Description |
|--------|----------|-------------|
| `--fqbn` | yes | Same as `compile`. |
| `--sketch` | yes | Sketch directory. |
| `--port` | yes | Serial device, e.g. `/dev/cu.usbmodem14101` or `COM3`. |
| `--build-path` | no | Build directory (default: same as `compile`, `<sketch>/build`). |
| `--output-dir` | no | Alias for `--build-path` when `--build-path` is not set. |
| `--ide-version` | no | Same default as `compile`. |
| `--no-preprocessor` | no | Same meaning as `compile` (must match how the build was produced if you rely on sketch.cpp layout). |
| `--dry-run` | no | Print the upload command only; do not run it. |
| `--no-object-cache` | no | Same as for `compile`: skip the shared object cache when resolving the build plan. |
| `--warnings LEVEL` | no | Same as `compile`: ``compiler.warning_flags.<LEVEL>`` from ``platform.txt``. |
| `--build-property KEY=VALUE` | no | Same as `compile`: override one platform/board property (repeatable). |

Examples:

```bash
acmake upload --fqbn arduino:avr:uno --sketch /path/to/Blink --port /dev/cu.usbmodem14101
acmake upload --fqbn espressif:esp32:esp32s3 --sketch /path/to/Sketch --port /dev/cu.usbserial-* --dry-run
acmake upload --fqbn arduino:avr:uno --sketch /path/to/Blink --port COM5 --build-path /tmp/mybuild
```

## `acmake board`

List installed board FQBNs discovered from the data directory, user directory, and optional sketch-local `hardware/` trees.

| Option | Required | Description |
|--------|----------|-------------|
| `--sketch DIR` | no | Repeatable. For each sketch, also list boards under `<sketch>/hardware/…`. |

Examples:

```bash
acmake board
acmake board --sketch /path/to/MySketch
acmake board --sketch /path/to/A --sketch /path/to/B
```

## Environment variables

Same semantics as Arduino CLI:

- **`ARDUINO_DIRECTORIES_DATA`** — data directory (cores, built-in tools).
- **`ARDUINO_DIRECTORIES_USER`** — user directory (sketchbook, user `hardware/`, `libraries/`). If unset, acmake uses **`~/Arduino`** on Linux and **`~/Documents/Arduino`** on macOS and Windows (same idea as Arduino IDE defaults).

You can override per invocation with `--data-dir` and `--user-dir`.

## Custom cores next to a sketch

If a core lives under the sketch (portable layout), put it at:

`<sketch>/hardware/<vendor>/<arch>/<version>/` (with `platform.txt` and `boards.txt` like Board Manager packages).

`compile` / `upload` resolve **sketch `hardware/` first**, then the sketchbook `hardware/` folder, then `Arduino15/packages/`. When choosing a version folder under `hardware/<vendor>/<arch>/`, only subdirectories that contain **`platform.txt`** are considered (so a sibling **`libraries/`** tree does not get mistaken for a core release).

Tools are still resolved from `packages/` and from that platform’s own `tools/` directory when present.

## Limitations

Cores that do not use `recipe.c.combine.pattern` / standard objcopy recipes may need extra support. Conformance is validated incrementally against installed `arduino-cli` where available.
