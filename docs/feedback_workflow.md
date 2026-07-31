# Feedback & issue tracking workflow (git-bug)

How external feedback, like the two review documents that used to sit in
`temporary/Feedback_1.txt` / `Feedback_2.txt`, gets turned into tracked,
actionable, non-lost work items.

## Why git-bug

[git-bug](https://github.com/git-bug/git-bug) stores bugs as git objects in
their own ref namespace (`refs/bugs/*`), not in a separate database or a
web-only service. That gives us three things a plain GitHub/GitLab Issues
board doesn't, for free:

- **Offline-first.** File/close/comment on bugs with no network, exactly
  like committing. Sync later with `git bug push`/`git bug pull`, the same
  mental model as `git push`/`git pull` for branches.
- **Lives with the code, forever.** A bug references file paths, line
  numbers, commit-shaped resolutions, and travels with the repo (clone,
  fork, mirror) instead of being stranded on one vendor's servers.
- **Bridges to GitHub/GitLab, doesn't replace them.** git-bug isn't "instead
  of" GitHub Issues; a bridge syncs bugs both ways, so collaborators who
  only use the GitHub web UI still see and can comment on the same bugs.

This repo's actual issue tracker link (`pyproject.toml`'s `Bug Tracker`
URL) still points at GitHub Issues; nothing about the public-facing entry
point changes. git-bug is the *local, offline-capable* half of the
workflow; the bridge keeps GitHub in sync for everyone else.

## One-time setup

```sh
# Install (no package manager entry yet; grab the release binary)
curl -sL https://github.com/git-bug/git-bug/releases/latest/download/git-bug_linux_amd64 \
    -o ~/.local/bin/git-bug && chmod +x ~/.local/bin/git-bug

# Create your identity once per machine (reuses git config user.name/user.email)
git bug user new --name "$(git config user.name)" --email "$(git config user.email)"
```

### Bridging to GitHub (do this once, needs a token)

```sh
# Token needs 'public_repo' scope (public repo): https://github.com/settings/tokens
git bug bridge new \
    --name=github \
    --target=github \
    --owner=MQSdk \
    --project=qpubench \
    --token=$GITHUB_TOKEN

git bug bridge push github    # push local bugs -> GitHub Issues
git bug bridge pull github    # pull GitHub Issues -> local bugs
```

GitLab is the same shape (`--target=gitlab --url=... --token=...`) if the
canonical remote ever moves there instead.

**Not run yet in this repo**: creating the bridge requires a personal
access token and the first `bridge push` creates real, visible GitHub
issues, which is a call for whoever owns the `MQSdk/qpubench` GitHub repo to
make, not something to do silently as part of an unrelated task.

## Intake workflow: turning feedback into bugs

When feedback arrives (a review document, a Slack message, a call
transcript, a raw `.txt` file dropped in `temporary/`), the general shape:

1. **Split it into discrete, actionable items.** One bug per distinct point
   and not one giant bug per document. A 6-bullet feedback email becomes up
   to 6 bugs. This keeps status (open/closed) meaningful per-item instead
   of one bug staying "open" for months because 1 of 6 points is unresolved.
2. **File each with `git bug bug new`**, non-interactively so it's
   scriptable:

   ```sh
   git bug bug new --non-interactive \
       -t "Short, specific title" \
       -m "Full context: what was said, why it matters, what file/slide
   it refers to. Include the resolution once you have one; bugs don't
   need to start empty and get filled in later, and a closed bug with no
   resolution note is nearly as useless as no bug at all."
   ```

3. **Label it.** This repo's convention so far:
   - `reviewer-feedback`: came from an external review pass
   - `schema-review`: came from an internal cross-schema review of the core
     record format; the finding is written up in
     [schema_review.md](schema_review.md) and sequenced in
     [roadmap.md](roadmap.md)
   - `docs` / `enhancement` / `bug`: what kind of change it needs
   - `follow-up`: a gap noticed *while* fixing something else, not the
     original ask
   - `partially-resolved`: some sub-points fixed, others intentionally
     deferred (say which, in the bug body)

   ```sh
   git bug bug label new <id> reviewer-feedback docs
   ```

4. **Close it with the resolution recorded**, not just a status flip:

   ```sh
   git bug bug status close <id>
   ```

   The body should already say *what changed* (file, slide, function), so that
   `git bug bug show <id>` should be enough on its own to understand both
   the original complaint and the fix, without needing to dig through
   `git log`.

5. **Leave genuinely open items open.** Not every piece of feedback gets
   resolved in the same pass; a follow-up discovered mid-fix (e.g. "this
   adapter doesn't exist yet either") is exactly what `git bug bug new`
   without a `status close` is for.

### Not only external feedback

The same intake works for findings the project generates about itself. The
2026-07-29 cross-schema review ([schema_review.md](schema_review.md)) produced
13 findings about the core record format; each was filed as one bug labelled
`schema-review`, and [roadmap.md](roadmap.md) sequences them into phases.

That split is deliberate and worth copying for the next review:

| Where | Holds | Changes when |
|---|---|---|
| `schema_review.md` | the evidence: what is missing and why it matters | a finding is applied (say so) or disproved |
| `roadmap.md` | the plan: phases, acceptance criteria, what is explicitly *not* being done | an item lands or is re-prioritised |
| git-bug | the status | continuously |

Duplicating status into the markdown is how a roadmap rots. Duplicating the
evidence into a bug body is fine; a bug should stand alone.

### Example: this session's intake

Feedback_1.txt/Feedback_2.txt were split into 13 discrete bugs (5 schema/
framework points, 8 slide points), each resolved and closed with a
resolution note referencing the actual files changed, plus 4 follow-up
bugs for gaps noticed while fixing them (schema-only error-mitigation
vendors, QDK's unmodeled circuit optimization, QPE having no runnable
adapter, and a deeper slide-restructuring pass still worth doing). Run
`git bug bug` in this repo to see the current list, `git bug bug show
<id>` for any one of them in full.

## Day-to-day commands

```sh
git bug bug                      # list all bugs (open + closed)
git bug bug --status open        # just open ones
git bug bug show <id>            # full thread for one bug
git bug bug comment new <id> -m "progress update"
git bug termui                   # terminal UI, if you'd rather browse than type commands
git bug webui                    # local web UI on localhost
git bug push && git bug pull     # sync refs/bugs/* with the git remote, like any branch
```
