# Open-core source and desktop release path

The release path produces one reviewed open-core snapshot and uses that same
snapshot for both public source and the Windows desktop installer.

```text
private development repository
          |
          v
allowlist publisher + boundary validator
          |
          +--> public repository main branch
          |
          +--> Python sidecar --> Tauri --> NSIS installer
                                      |
                                      v
                           public GitHub Release
```

This prevents the installer from quietly containing code that is absent from
the public repository. The validator also rejects custom SVG/IBCS and Tableau
visual UI and requires all 31 Plotly visual types and all 17 connectors.

## One-time GitHub setup

1. Create the separate public repository and initialize its target branch
   (normally `main`) with any commit. The workflow replaces the branch contents
   while preserving its `.git` directory.
2. In this private repository, create the Actions variable
   `OPEN_CORE_PUBLIC_REPOSITORY` with the value `owner/repository`.
3. Add `OPEN_CORE_RELEASE_TOKEN` as an Actions secret. Use a fine-grained token
   restricted to the public repository with **Contents: Read and write**.
4. Protect the public `main` branch as desired, but allow the release token to
   update it. The public repository receives its own `open-core-ci.yml` workflow.
5. Optional: add `WINDOWS_CERTIFICATE_PFX_BASE64` and
   `WINDOWS_CERTIFICATE_PASSWORD` to Authenticode-sign the Windows bundle.

The workflow uses the separate token only when `publish=true`. A manual dry run
therefore needs no public-repository write and cannot publish anything.

## Dry run

Open **Actions > Release Open Core > Run workflow** and supply a semantic
version such as `0.1.0-alpha.2`. Keep `publish` disabled. GitHub will:

1. synchronize Python, npm, Cargo, and Tauri versions;
2. generate and validate the clean source tree;
3. run the public tests and frontend build;
4. build and smoke-test the PyInstaller backend;
5. build and smoke-test the Tauri/NSIS desktop application;
6. upload the installer, deterministic bundle, source ZIP, and SHA-256 files as
   private workflow artifacts.

## Publish a release

After a successful dry run, either rerun manually with `publish=true`, or push
an immutable private-repository tag:

```powershell
git tag open-core-v0.1.0-alpha.2
git push origin open-core-v0.1.0-alpha.2
```

A release tag automatically enables publication. The public source branch is
updated first; GitHub then creates `v0.1.0-alpha.2` in the public repository and
attaches:

- the raw NSIS setup executable;
- `Dummy-BI-Engine-<version>-windows-x64.zip`;
- `Dummy-BI-Engine-Windows-x64-Setup.exe` as the permanent latest-download asset;
- bundle and source checksums;
- the validated source ZIP.

Existing public tags or releases are never overwritten. Use a new version for
every release.

## Local source validation

```powershell
python tools/publish_open_core_mvp.py --output dist/open_core_mvp
python tools/validate_open_core_mvp.py dist/open_core_mvp
```

The local publisher only creates files under `dist`; it never commits, pushes,
or creates a GitHub release.

## First-version recommendation

Ship the NSIS installer and public source together as a prerelease. Do not add
automatic application updates to the first feedback build: the reference
project's updater requires stable signing keys, hosted updater metadata, and a
long-term update URL. Add that only after the application identity and signing
process are stable.
