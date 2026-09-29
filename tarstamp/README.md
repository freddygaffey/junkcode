# tarstamp

> One-shot timestamped tar snapshots. The panic button before a risky change.

`tarstamp` is a tiny shell function that creates a timestamped `.tar` archive of a file or directory. No config, no daemon, no compression overhead — just a fast, predictable snapshot you can roll back to when something goes wrong.

```sh
$ tarstamp ardupilot
→ ardupilot_20260518_143000.tar | 12.3s | 847M
```

That's the whole thing.

## Why

You're about to do something risky — a big refactor, a `git rebase`, swap a config, test an experimental branch. You want a panic button: a frozen copy of the current state you can restore in one command if it all goes wrong.

`git stash` is great when the change stays inside git. `tarstamp` covers everything else: build artifacts, generated files, untracked junk, the `.git` directory itself, configs scattered across a project. One command, one tarball, named after the directory and stamped with the time.

It is intentionally not a backup tool. No deduplication, no encryption, no scheduling. If you want those, use [restic](https://restic.net/) or [borg](https://www.borgbackup.org/). `tarstamp` is for the next five minutes.

## Install

### Linux / macOS / WSL / Git Bash

```sh
curl -fsSL https://raw.githubusercontent.com/freddygaffey/tarstamp/main/install.sh | sh && . ~/.tarstamp.sh
```

Adds a source line to `~/.bashrc`, `~/.zshrc`, and `~/.bash_profile` (whichever exist), then loads `tarstamp` into the current shell. New shells pick it up automatically.

### Windows (PowerShell / pwsh)

```powershell
irm https://raw.githubusercontent.com/freddygaffey/tarstamp/main/install.ps1 | iex; . "$HOME\.tarstamp.ps1"
```

Adds a source line to your PowerShell `$PROFILE`, then loads `tarstamp` into the current session. Requires `tar` on PATH (ships with Windows 10 1803+; otherwise install Git for Windows).

### Manual

Download `tarstamp.sh` (Unix) or `tarstamp.ps1` (Windows) and source it from your shell rc.

## Usage

```sh
tarstamp <path>             # archive a file or directory
untarstamp <archive.tar>    # extract into <archive>.extracted/
```

Single argument only. Output lands in the current directory, named `<path>_<YYYYMMDD_HHMMSS>.tar`. Tab-completion works on bash and zsh.

```sh
$ tarstamp src/
→ src_20260518_143215.tar | 0.4s | 12M

$ untarstamp src_20260518_143215.tar
→ ./src_20260518_143215.extracted
```

## Design choices

- **No compression.** Most snapshots are short-lived. Saving 10 seconds of wall time matters more than saving 30% of disk. If you need compression, pipe through `gzip` yourself.
- **One argument.** Predictable naming. Globs (`tarstamp *.py`) fail loudly rather than producing a confusingly-named archive.
- **Current directory output.** The archive lands next to what you snapshotted. Easy to spot, easy to delete.
- **Timestamp in the filename.** Sortable, readable, unique per second.

## Platform notes

| Platform           | Status | Notes |
|--------------------|:------:|-------|
| Linux (bash, zsh)  | yes    | Primary target. |
| macOS (bash, zsh)  | yes    | Uses `perl` for sub-second timing (ships with macOS). |
| Windows PowerShell | yes    | Needs `tar` on PATH (built into Windows 10 1803+). |
| Git Bash / WSL     | yes    | Same as Linux. |

## Uninstall

Delete `~/.tarstamp.sh` (or `~/.tarstamp.ps1`) and remove the source line from your shell rc.

## License

MIT.
