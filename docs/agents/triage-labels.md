# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

This repo deliberately does **not** create dedicated triage labels. We map the five
roles onto GitHub's stock label set, which is all `vivi930319/DecorateMeAI` carries.
Do not invent new label strings — if a role has no label here, it has no label.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | _(no label)_         | Maintainer needs to evaluate this issue  |
| `needs-info`               | `question`           | Waiting on reporter for more information |
| `ready-for-agent`          | `good first issue`   | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `help wanted`        | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

The two category roles need no translation: `bug` and `enhancement` already exist
under those exact names.

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the
corresponding label string from this table.

## Consequences of mapping onto stock labels

Two of these are lossy. Know about them before running `/triage`:

- **`needs-triage` has no label of its own.** `/triage` normally separates
  "never triaged" (unlabeled) from "triaged, awaiting the maintainer's decision"
  (`needs-triage`). Here both are the absence of a state label, so those two
  buckets are one bucket. The practical effect: an issue that has been read and
  parked looks identical to one nobody has opened. If that distinction starts to
  matter, say so — creating a real `needs-triage` label is a one-line fix.
- **Moving *to* `needs-triage` means removing a label, not adding one.** When the
  state machine says "return #42 to `needs-triage`" (e.g. the reporter replied to
  a `needs-info`), strip the state label and add nothing.

`good first issue` and `help wanted` are also carrying meanings GitHub's UI
advertises to outside contributors ("newcomers welcome", "we want help"). In this
repo they mean the triage states above. Nothing about the project invites drive-by
contributors, so the clash is theoretical — but it is why these labels look odd on
issues that are clearly not beginner work.

If new labels ever do get created, update the right-hand column and delete this
section.
