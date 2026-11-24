# App troubleshooting

Last reviewed: 2026-11-23

This page covers the frozen zipseal window: the downloaded `.dmg`, AppImage or
`.tar.gz`. It does the same job as the `zipseal` command, so archive problems
are usually the same; see [opening the archives](opening-archives.md) and the
[security notes](security.md). A `zipseal-gui` installed with `uv tool install`
is not frozen and needs Python and `uv`; this page is not about that install.

## Which build do I have?

The frozen window does not show a version. The download filename and the
[release page](https://github.com/kgforais1/zipseal/releases) do.

| Platform | Artifact | Requirements |
|---|---|---|
| macOS | `zipseal-gui-<version>-macos-arm64.dmg` | macOS 11 or later, Apple silicon; signed and notarized |
| Linux (v0.3.0 or later) | `zipseal-gui-<version>-linux-x86_64.AppImage` or `.tar.gz` | x86_64; glibc 2.35 or later |
| Windows | Not yet available | The core filesystem port is still in progress |

The Linux artifacts are published starting with v0.3.0. The
[CLI source install](../README.md#install-the-cli) remains available on every
platform.

## macOS

The downloaded app is signed and notarized, so Gatekeeper should open it
without a warning. If macOS still blocks it, open System Settings → Privacy &
Security and press **Open Anyway** next to the zipseal message
([Apple's guide](https://support.apple.com/en-ie/102445)).

The `zipseal-gui.command` launcher used from a clone is a script, not the
signed app. If macOS quarantines that file, use **Open Anyway** or run:

```sh
xattr -d com.apple.quarantine zipseal-gui.command
```

The macOS app is Apple silicon only. An Intel Mac needs the source install
until an Intel artifact exists.

## Linux

The Linux build is x86_64 only. Check the glibc version with `ldd --version`;
the first line must be 2.35 or later. Older distributions will not run this
build.

Set `VERSION` to the release you downloaded (for example, `0.3.0`), then run
the AppImage:

```sh
VERSION=0.3.0
chmod +x "zipseal-gui-${VERSION}-linux-x86_64.AppImage"
./"zipseal-gui-${VERSION}-linux-x86_64.AppImage"
```

If FUSE is unavailable, use the extraction fallback:

```sh
./"zipseal-gui-${VERSION}-linux-x86_64.AppImage" --appimage-extract-and-run
```

For the tarball, extract it and run the binary from the extracted folder:

```sh
tar -xzf "zipseal-gui-${VERSION}-linux-x86_64.tar.gz"
./zipseal-gui/zipseal-gui
```

The tarball runs from any folder. If the window does not appear, run the
binary from a terminal; it prints the error there. The window needs an X11 or
Wayland display; over SSH, use the CLI instead.

## Windows

There is no Windows build yet. The Windows app is deferred until the core
filesystem port lands (see [`TODO.md`](../TODO.md)). There is no Windows asset
on the release page yet.

When a Windows build ships, SmartScreen and Smart App Control may warn about a
new, unsigned PyInstaller executable, and some antivirus tools flag PyInstaller
builds as false positives. The release will include `SHA256SUMS` and build
provenance; compare the download before deciding. The Windows build will get
its own troubleshooting notes when it ships.

## Where does it write?

Only where you tell it to. The archive, and its `.temp` working files while a
run is in progress, are written next to the output name you choose. The
window keeps no settings, no history and no password. It makes no network
requests.

If a run is killed, it can leave `.temp` files next to the output. Delete them
before the next run; the window refuses to overwrite an output it cannot
safely replace.

## The generated password is gone

The generated password is shown once, in the modal after a successful run.
There is no recovery and no password stored in the archive metadata. If it is
lost, delete the archive and create it again with a new password.

Copy it with the modal's **Copy** button, or select it and copy it. zipseal
clears that clipboard entry when you close the modal and again 60 seconds after
you copy. Other applications can read the clipboard in between, so copy it and
move on.

## The archive will not open

On macOS 11 or later, Finder opens AES zips; 7-Zip and Keka also work. On
Linux and Windows, use 7-Zip or `bsdtar`. macOS's `/usr/bin/unzip` cannot open
AES zips. See [opening the archives](opening-archives.md) for the tool-by-tool
details.

## Antivirus warnings

The builds are PyInstaller `onedir` bundles, which some antivirus engines flag
as false positives. The macOS app is signed and notarized; Linux artifacts are
not code-signed. Every release publishes `SHA256SUMS` and a build provenance
attestation, and the build runs from the tagged commit. Verify the download
before treating a warning as a zipseal problem.

## See also

- [The zipseal window](gui.md): what each control does.
- [Opening the archives](opening-archives.md): which tools open AES zips.
- [Security notes](security.md): what the password protects and what it does not.
