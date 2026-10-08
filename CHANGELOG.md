# Changelog

All notable user-facing changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `zipseal PATH... -o OUT.zip` writes one AES-256 (WinZip AE-2) zip,
  verifies it, and publishes it without overwriting existing files.
- Password from a prompt, an environment variable, a file, or
  `--generate-password`.
- `--dry-run`, `--exclude`, `--follow-symlinks`, `--level`, `--force` and
  `--no-verify`.
