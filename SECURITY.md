# Dummy BI Engine security model

## Supported open-core deployment

The supported public build is a single-user, local desktop authoring tool. The
Tauri shell starts its backend on the loopback interface (`127.0.0.1`) and uses
a random per-process desktop token on every API request. Do not expose the
development server to another machine or bind it to a public network interface.

Local author mode deliberately lets the signed-in operating-system user choose
workspaces, databases, import files, export destinations, and connector files.
Those paths are user intent, not a cross-user authorization boundary. A caller
that does not already have the desktop token cannot use the local API to select
them.

The repository also contains server-mode boundary code used by the broader
product. When `DAX_SERVER_MODE=server`, project resolution is restricted to the
configured `DAX_PROJECT_PATH`; the public feedback build is not supported as a
multi-user or internet-facing server.

Power Query credential metadata is redacted before it is written. Secret
payloads use Windows DPAPI in the desktop build and authenticated local
encryption on non-Windows development systems. Tests assert that known
plaintext values never appear in either the metadata file or secret store.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting for this repository. Do not
post credentials, private datasets, customer paths, or exploit details in a
public issue. Include the version, operating system, affected feature, minimal
reproduction, and impact.

If private GitHub reporting is unavailable, open an issue with minimal detail
and ask the repository owner for a private channel.

## Supported versions

Dummy BI Engine is currently in alpha. Security fixes are released as patch
versions, and only the latest release is supported.
