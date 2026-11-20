# SPK Builder · Synology DSM Package Build Service

A **native package build service that runs on the Synology DSM system**: once packaged as a `.spk` and installed on DSM, you can pack / unpack / batch-process `.spk` packages right from the browser — no command line needed.

> **中文**: [README.md](README.md)

## Install on DSM

1. **Dependency**: install SynoCommunity's `python311` (Python 3.11 runtime) from Package Center.
2. **Service**: build `spkbuilder_<model>.spk` with the "Package as a native .spk" section below (or download it from Releases); set Package Center **Settings → Trust level** to **Any publisher** and install manually.
3. **Open**: browse to `http://<NAS-IP>:8800` to enter the build console.

## Use on DSM

### 🚀 Pack `.spk`

Put the files to install into a directory whose layout maps to the installed `target/`, then fill in the form and build:

```
mypkg/
├── bin/myapp            # executable (packed as 0755)
├── ui/                  # optional: DSM UI files
├── conf/                # optional: config files
├── scripts/             # optional: lifecycle scripts (auto-generated if missing)
├── PACKAGE_ICON.PNG     # optional: icon (placeholder auto-generated if missing)
└── PACKAGE_ICON_256.PNG
```

- Fill in the **package info** (name / version / description / maintainer, etc.);
- Select the **target architecture(s)** (`x86_64` / `armv7` / `arm64` / `noarch`);
- Click **🚀 Build**, watch the live log, then download the `.spk`.

For multi-arch, place per-arch binaries in subdirectories (`x86_64/bin/myapp`, `arm64/bin/myapp`, etc.).

### 📥 Unpack / re-pack

Import an existing `.spk`, analyze it, and auto-fill the form; tweak it (version / description / maintainer, etc.) and re-pack. The "Open" button, dependency declarations, symlinks, `conf/privilege`, and other metadata are preserved.

### 📦 Batch

Import multiple `.spk` files, edit each independently, batch-edit a single field, build in parallel, and download as a zip (organized into `<name>-dsm7/` folders).

## Features

| Feature | Description |
| --- | --- |
| Native runtime | Package itself into a native `.spk` and run non-root with a File Station shared folder |
| Pack `.spk` | Produces the standard layout: INFO + package.tgz + scripts/ + icons |
| Unpack & re-pack | Import an existing `.spk`, auto-fill the form, preserve metadata |
| Per-model distribution | Automatically writes the full model list into the INFO `arch` field |
| Batch | Batch unpack / edit / build / download |
| Zero dependencies | Packing only uses the Python standard library |

## Model distribution (Package Center model matching)

Each `.spk` automatically writes the full model list for its architecture family into the INFO `arch` field (family code first + specific model codes), so DSM Package Center matches the package to the exact device model:

| Arch | INFO `arch` field content (excerpt) |
| --- | --- |
| `x86_64` | `x86_64 apollolake avoton braswell broadwell broadwellnk broadwellnkv2 broadwellntbap bromolow cedarview denverton epyc7002 epyc7003 geminilake geminilakenk grantley icelaked kvmx64 purley r1000 r1000nk v1000 v1000nk` |
| `arm64` | `armv8 arm64 aarch64 rtd1296 rtd1619b armada37xx` |
| `armv7` | `armv7 armada370 armada375 armada38x armadaxp alpine alpine4k monaco comcerto2k hi3535` |
| `noarch` | `noarch` (all models) |

> Note: `arm64` writes `armv8` / `arm64` / `aarch64` together — sspks-imnks uses `armv8` as the family, so writing only `arm64` would make ARM models fail to match.

## Package as a native .spk (deploy to DSM)

The service can package **itself** into a native Synology `.spk` (run once on a machine):

```bash
python build_self.py
```

- **Non-root**: runs as a dedicated `sc-spkbuilder` user in the `synocommunity` group;
- **File Station shared folder**: auto-creates a shared folder at install time for build output;
- **SynoCommunity standard layout**: generic `scripts/functions` + `installer` + `service-setup` + `start-stop-status` framework;
- **Per-model packages**: 1:1 aligned with [sspks-imnks](https://github.com/tbc0309/sspks-imnks)'s `conf/synology_models.yaml` — one package per model (`spkbuilder_<model>.spk`).

Output is in `output/spkbuilder-1.0.1/`.

## Working with an sspks package source

Drop the generated `.spk` into the `packages` directory of an [sspks](https://github.com/tbc0309/sspks-imnks) server, then add the server address in **Package Center → Package Sources** to install.

> On DSM 7, manually installing an unsigned third-party package requires setting the **Trust level** to **Any publisher** in Package Center settings.

## Local development mode (optional, cross-compilation)

On DSM you mainly pack / unpack / batch. To **cross-compile from source** (requires a toolchain), run `python server.py` on a machine and use:

- **Go**: local Go cross-compilation (`CGO_ENABLED=0` static binaries);
- **Docker**: run arbitrary compile commands in a container (C/C++, etc.);
- **Local command**: run any command (`$OUT_BIN` / `ARCH`);
- **spksrc**: compile native programs with SynoCommunity's [spksrc](https://github.com/SynoCommunity/spksrc) framework (WSL2).

## Directory layout

```
spk-builder/
├── server.py          # backend service (HTTP + build jobs + artifact download)
├── spkpack.py         # packing core (generates INFO/scripts/package.tgz/.spk)
├── builders.py        # build providers & toolchain detection
├── build_self.py      # packaging script (builds this service into a native .spk)
├── packaging/         # framework / service config / install wizard for packaging
├── web/               # frontend (index.html / app.js / style.css)
├── 更新日志.txt        # changelog (data source for the web "Changelog" tab)
└── output/            # build artifacts (generated at runtime)
```

## FAQ

- **"Unable to correctly install this package"**: make sure `python311` is installed and Package Center trust level is "Any publisher".
- **Non-root**: the service runs non-root as `sc-spkbuilder`; build output goes to the shared folder created at install time.
- **Download path**: download links point to relative paths under `output/`, named `<name>_<arch>-<version>.spk`.

## License

[MIT](LICENSE)
