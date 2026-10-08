# zipseal developer docs

Last reviewed: 2026-10-08

This folder holds documentation for people and agents who build `zipseal`.
User-facing documentation lives in [`../user-docs/`](../user-docs/).

## Layout

| Path | Holds | Lifetime |
|---|---|---|
| `plans/` | Active implementation plans, named `YYYY-MM-DD-slug.md` | Until complete or abandoned |
| `plans/archive/` | Completed and abandoned plans | Permanent |
| `investigations/` | Research, spikes, benchmarks and bug write-ups, named `YYYY-MM-DD-slug.md` | Permanent, never rewritten |
| `decisions/` | Architecture decision records, added when the first one is needed | Permanent, superseded rather than edited |

`SPEC.md` at the repo root is the design. Plans say how and in what order to
build it. If a plan changes the design, update `SPEC.md` in the same commit.

`.context/` is gitignored scratch space. Nothing there is the source of truth.
Move anything worth keeping into `investigations/` or a plan.

## Where things go

| You have… | Put it in |
|---|---|
| Work nobody has started | `TODO.md`, one line each |
| Work that needs steps, choices or a test list | A new plan in `plans/`, linked from `TODO.md` |
| Findings from research or a spike | `investigations/` |
| A hand-off between agents or sessions | `.context/handoff.md` |
| Finished work users can see | `CHANGELOG.md` |
| Finished internal work | `CHANGELOG.dev.md` |

`TODO.md` never records finished work. Delete the item when it lands and log it
in a changelog instead.

## Plan lifecycle

Every plan starts with this header:

```
# Plan: <title>

Date: YYYY-MM-DD
Status: draft | approved | in-progress | complete | abandoned
Linked: <TODO item, issue or PR>
```

1. **draft.** The plan is written but not approved. Get it reviewed before work
   starts.
2. **approved.** The user accepted the plan. Record review changes in the plan
   itself, not in chat.
3. **in-progress.** Work follows the checklist. Tick a box only when the task is
   done and verified by a test, a command or explicit acceptance. If a task is
   blocked, leave it unticked and add a note under it. Do not weaken the task to
   get past it.
4. **complete** or **abandoned.** Set the status. For an abandoned plan, add one
   line saying why. Then run the completion steps below.

### Completion steps

Do all of these in the commit that finishes the plan:

1. Set `Status:` to `complete` or `abandoned`.
2. Move the file to `plans/archive/` with `git mv`. Never delete a plan.
3. Log the work in `CHANGELOG.md` or `CHANGELOG.dev.md`. Link the plan.
4. Delete the matching items from `TODO.md`.
5. Delete related scratch files from `.context/`.
6. Update `SPEC.md` if the built behavior differs from it.

Keep each plan under about 600 lines. Split a larger effort into phased plans
that link to each other.

## Doc gardening

Stale docs mislead agents more than missing docs do. These rules keep docs
honest:

- Durable docs carry `Last reviewed: YYYY-MM-DD` near the top. That covers
  `AGENTS.md`, `SPEC.md`, `TODO.md`, the two `README.md` files in `user-docs/`
  and `dev-docs/`, and every page in `user-docs/`. The pre-commit hook
  `check-doc-freshness` blocks a missing marker. It warns after 180 days and
  blocks after 365.
- Bump the date only after re-reading the doc against the current code. The
  date asserts that someone checked.
- Plans and investigations are dated by their file name and are exempt.
- When code changes behavior, update the doc that describes it in the same
  commit. That includes `SPEC.md`, `AGENTS.md` commands and `user-docs/`.
- At each milestone, run a gardening pass. Check every `Last reviewed` date.
  Prune `TODO.md`. Archive finished plans. Grep source for stale
  `TODO`/`FIXME` comments. Run `uvx vulture src` and `uvx deptry .` for dead
  code and unused dependencies.

## Hooks that enforce this

| Hook | Script | Rule |
|---|---|---|
| `check-doc-freshness` | `hooks/scripts/check_doc_freshness.py` | `Last reviewed` marker present and recent |
| `check-todo-limits` | `hooks/scripts/check_todo_limits.py` | `TODO.md` warns at 150 lines, blocks at 300 |
| `check-file-size` | `hooks/scripts/check_file_size.py` | Source warns at 600 lines, blocks at 1000 |
