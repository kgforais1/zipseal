# TODO

Last reviewed: 2026-10-08

Future work only. Each item is something nobody has started or finished.

When an item is done, delete it from this file in the same commit. Log the
work in `CHANGELOG.md` if users can see it, or in `CHANGELOG.dev.md` if they
cannot. Never mark items `[x]` here, and never keep a "done" section.

An item that needs more than a few lines of thought gets a plan in
`dev-docs/plans/`. Link it from the item.

## Next

- Implement v1 per [`dev-docs/plans/2026-10-08-v1-implementation.md`](dev-docs/plans/2026-10-08-v1-implementation.md).
- Add CI. Run pre-commit, pytest and a dependency audit on push and pull
  request with GitHub Actions. Add Dependabot for `uv` and Actions.

## Later

- Resolve the open questions in `SPEC.md` §9.
- Consider `--format 7z`, `--oversize=volumes` and `--tight` (`SPEC.md` §6.2, §6.4, §6.7).
