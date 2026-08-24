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
the public repository. The validator rejects excluded implementation source and
requires the shared shell, all 31 Plotly visuals, table, all 17 connectors, and
the signed updater configuration.

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
6. Add `TAURI_UPDATER_PUBLIC_KEY` as an Actions variable and
   `TAURI_SIGNING_PRIVATE_KEY` plus `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` as
   Actions secrets.

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
- `Dummy-BI-Engine-Open-Core-<version>-windows-x64.zip`;
- the signed Dummy BI Engine installer and `.sig` file;
- `latest.json` for the Tauri updater;
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

## Updater key handling

The updater endpoint is the public repository's root `latest.json`. Never rotate
the private updater key without a transition plan for applications that already
embed the current public key.
