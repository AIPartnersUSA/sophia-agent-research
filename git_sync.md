# git_sync.md — keeping local Mac + EC2 + GitHub in sync

This is the operational procedure for the recurring "I edited code in two places, what's the safe way to reconcile them?" problem.

The three machines:

- **LOCAL** = Avinash's Mac. The repo at `/Users/avinashbolleddula/Documents/sophia Agent Research/`. Unity / Mac-only files live here.
- **EC2** = the shared GPU EC2 (3.227.63.49). The repo at `/workspace/avinash/sophia/`. Production-runtime files live here.
- **REMOTE** = GitHub. The repo at `git@github.com:AIPartnersUSA/sophia-agent-research.git`. The shared source of truth.

Where each kind of file BELONGS:

| File family | Edited on | Reason |
|---|---|---|
| Unity scripts (`sophia-glasses/unity/Assets/Scripts/*.cs`) | LOCAL only | Unity is not installed on EC2. |
| Frontend code (`agent-starter-react/*`) | Either | Built into static bundle; can be edited on whichever machine is running it. |
| Backend code (`sophia-agent/src/*`) | Either | Runs in container; edits work in either place but EC2 is where the live demo runs. |
| Docker config + `docker-compose.yml` at workspace root | EC2 (canonical) | EC2 is where the stack actually runs. Local can have a copy for reference. |
| `.env.production`, `livekit.prod.yaml` (secrets) | EC2 only | Never committed. Gitignored. |
| Research / operational `.md` docs at repo root | LOCAL (canonical) | Where the human writes them. |
| Memory files | LOCAL only | Lives outside the repo under `~/.claude/projects/...`. |

---

## Snapshot of the divergence this file was written to handle (2026-05-29)

After the MVP demo prep day, the three machines drifted:

- **LOCAL had:** doc audit edits (6 .md files), Unity X-API-Key client changes (SophiaConfig.cs + SophiaConnection.cs + SophiaConfig.asset), new `sophia_week3_presentation.html`. All uncommitted.
- **EC2 had:** removed-NODE_ENV-throw in `app/api/token/route.ts`, hardcoded `agentName: 'sophia-agent'` in `app-config.ts`, plus untracked `docker-compose.yml`, `frontend.log`, `livekit.prod.yaml`, plus accidental auto-format noise on 5 .tsx files, plus npm-regenerated `package-lock.json`.
- **REMOTE had:** neither set of changes. Matched LOCAL at the commit level (no commit divergence) but not the dirty-file level.

The 8-step procedure below was written to reconcile that specific state. The structure generalizes to any future sync.

---

## The 8-step procedure (do these in order)

### STEP 1 — On EC2: check what is dirty

SSH in. Look at `git status`. Confirm the changes you expect; flag anything you don't.

```bash
ssh sophia-gpu
cd /workspace/avinash/sophia
git status
```

Expected modified files: whatever you intentionally edited.
Expected untracked files: `frontend.log`, `.env.production` (gitignored), maybe `docker-compose.yml` if it's not yet tracked.

If you see anything else dirty, do NOT proceed. Diff it first (STEP 2A) to decide what it is.

### STEP 2A — Triage unexpected modified files

For each file you did NOT intentionally edit, look at the diff:

```bash
git diff <file>
```

Decision rule:

- If the diff is **whitespace, import reorder, quote style, prettier-style noise** → discard it. `git checkout -- <file>`.
- If the diff is **a real logic change** you remember making → keep it, stage it explicitly later.
- If you **don't remember either way** → diff carefully; default to discarding (you can always re-do the edit if it mattered).

For `package-lock.json` specifically: it's almost always a side-effect of `npm install` running on EC2. Discard it — keep LOCAL as the canonical lockfile, and EC2 will re-derive on next install.

```bash
git checkout -- agent-starter-react/package-lock.json
```

### STEP 2B — Decide each untracked file

For each untracked file, choose: commit it, gitignore it, or leave it as transient state.

Common cases:

- **`frontend.log`** → gitignore. Runtime log output.
  ```bash
  echo "frontend.log" >> .gitignore
  ```
- **`docker-compose.yml` at workspace root** → commit IF it doesn't contain inline secrets. Check first:
  ```bash
  grep -i -E "secret|key|password|token" docker-compose.yml
  ```
  If only references like `env_file: ./sophia-agent/.env.production` come back, it's safe — `git add docker-compose.yml`. If literal secret values, refactor to env_file first.
- **`sophia-agent/infra/livekit.prod.yaml`** → almost certainly has inline `api_key:` / `api_secret:` values (LiveKit yaml format). DO NOT commit. Gitignore it; document the schema in `mvp_deployment_shared_ec2.md`.
  ```bash
  echo "sophia-agent/infra/livekit.prod.yaml" >> .gitignore
  ```
- **`.env.production`** → already gitignored. No action needed.

### STEP 2C — Verify staging area, commit, push (from EC2)

Check status. You should see ONLY the intentional changes plus `.gitignore`.

```bash
git status
```

Stage everything:

```bash
git add .gitignore <each intentional file>
```

Commit with a descriptive message:

```bash
git commit -m "Shared EC2 demo deployment: production fixes + orchestration

- <file>: <what changed and why>
- <file>: <what changed and why>"
```

Push:

```bash
git push origin main
```

If push is rejected (someone else pushed first): `git pull --rebase origin main`, resolve any conflicts, then `git push origin main`.

### STEP 3 — On Mac: pull the EC2 commits down

Open a local terminal at the repo root.

```bash
cd "/Users/avinashbolleddula/Documents/sophia Agent Research"
git pull origin main
```

If pull complains about local uncommitted changes that overlap with the incoming files: stash first, pull, then unstash. `git stash` → `git pull` → `git stash pop`. Resolve any conflicts.

Verify the EC2 fixes landed:

```bash
grep -n "NODE_ENV" agent-starter-react/app/api/token/route.ts          # should be empty or just a doc comment
grep -n "agentName" agent-starter-react/app-config.ts                  # should show hardcoded value, not process.env
```

### STEP 4 — On Mac: handle the SophiaConfig.asset secret

`SophiaConfig.asset` holds the `SOPHIA_TOKEN_API_KEY` value. Even in a private repo, committing a real auth secret is bad hygiene.

**Option A (recommended):** Open Unity, set `tokenApiKey` back to empty string, save the asset. The schema change in `SophiaConfig.cs` (the new public field) still gets committed. A fresh clone has the field present-but-blank; each developer fills it in on their own machine. Document the rotation procedure in the runbook (already in `mvp_deployment_shared_ec2.md`).

After clearing in Unity:

```bash
git diff sophia-glasses/unity/Assets/Settings/SophiaConfig.asset
```

Should now show only structural changes (the new YAML key), no actual key value.

**Option B (accept risk for MVP):** Leave the key. Commit it. Add a TODO to rotate before real production deploy.

### STEP 5 — On Mac: clean up Unity build artifacts that are tracked by accident

Earlier sessions did `git add .` and accidentally tracked Unity build outputs. These regenerate on every build and create noise.

```bash
echo "sophia-glasses/unity/sophia-glasses_BackUpThisFolder_ButDontShipItWithYourGame/" >> .gitignore
echo "sophia-glasses/unity/.utmp/" >> .gitignore
git rm -r --cached sophia-glasses/unity/sophia-glasses_BackUpThisFolder_ButDontShipItWithYourGame
git rm -r --cached sophia-glasses/unity/.utmp
```

This removes from tracking without deleting from disk. Cleaner future commits.

### STEP 6 — On Mac: stage the local-canonical changes

```bash
git add .gitignore
git add git_setup.md livekit_deployment.md livekit_doubts.md mvp_deployment_shared_ec2.md production_deployment.md
git add sophia-glasses/READING_GUIDE.md
git add sophia-glasses/unity/Assets/Scripts/SophiaConfig.cs
git add sophia-glasses/unity/Assets/Scripts/SophiaConnection.cs
git add sophia-glasses/unity/Assets/Settings/SophiaConfig.asset
git add sophia_week3_presentation.html
git add git_sync.md  # this file, if first time saving it
```

Verify:

```bash
git status
```

Should show staged: docs, presentation, Unity scripts, asset, gitignore. Cached deletions of build artifacts if STEP 5 was done.

### STEP 7 — On Mac: commit and push

Two commits keep history readable; one is also fine.

**Commit A — Unity client X-API-Key auth:**

```bash
git commit sophia-glasses/unity/Assets/Scripts/SophiaConfig.cs sophia-glasses/unity/Assets/Scripts/SophiaConnection.cs sophia-glasses/unity/Assets/Settings/SophiaConfig.asset -m "Add X-API-Key auth on glasses token-mint requests

- SophiaConfig.cs: new tokenApiKey field (empty default = no auth header)
- SophiaConnection.cs: UnityWebRequest.Post conditionally sets X-API-Key header
- SophiaConfig.asset: schema-level field addition (key value not committed)"
```

**Commit B — docs + ops + presentation:**

```bash
git commit -m "Doc audit for 2026-05-29 MVP demo

- mvp_deployment_shared_ec2.md: Phase 12/13/14 + Sharing section + Problems 14-19 + cold-start hardening
- livekit_doubts.md: Q61 (two-auth-paths) + Q62 (network_mode: host rationale)
- production_deployment.md: Status block + Section 0 Keep/Replace/Defer + See-also
- sophia-glasses/READING_GUIDE.md: tokenApiKey in Step 4, X-API-Key in Step 7
- git_setup.md / livekit_deployment.md: cross-references touched up
- sophia_week3_presentation.html: NEW (week-3 team deck)
- git_sync.md: NEW (this file — sync procedure)
- .gitignore: untrack Unity build artifacts"
```

Push:

```bash
git push origin main
```

### STEP 8 — On EC2: pull the new commits

Back on EC2.

```bash
ssh sophia-gpu
cd /workspace/avinash/sophia
git pull origin main
```

If `git pull` complains about local uncommitted state: it should only complain if you have new dirty files since STEP 2. Check `git status` first. Untracked files like `.env.production` and now-gitignored files won't block.

### Final verification — all three match

On Mac:

```bash
git log --oneline -5
git status
```

On EC2:

```bash
git log --oneline -5
git status
```

The top log lines should be identical. `git status` should show clean on both, except for EC2's `.env.production` which is gitignored.

---

## Watch-fors and recovery paths

### Push rejected with "Updates were rejected"

GitHub has commits you don't. `git pull --rebase origin main` first, then re-push. If rebase produces conflicts, resolve them per-file with your editor, `git add` the resolved file, `git rebase --continue`.

### Pull complains about uncommitted overlap

`git stash` to set aside your dirty changes, `git pull`, then `git stash pop`. If stash pop produces conflicts, resolve manually.

### `git rm --cached` deletes thousands of files

Expected — Unity build folders contain massive trees. The deletions go into the commit as a hygiene cleanup. Files stay on disk; they're just no longer tracked.

### Accidentally committed a secret

```bash
# If not yet pushed: amend
git reset HEAD~1
# Re-edit to remove secret, then commit + push fresh

# If already pushed: rotate the secret IMMEDIATELY
# Then use git filter-branch or BFG to scrub history. Don't try this without a backup.
```

### EC2 has uncommitted state you didn't expect

Diff each file. Don't `git checkout --` blindly — you might lose someone else's intentional work. Surface the files to the team (if shared box) before discarding.

### Pull on EC2 modifies a file you're actively running

The frontend (`npm start`) and the docker stack continue running with the OLD code in memory. Restart them to pick up new code:

```bash
# Restart frontend
sudo fuser -k 3000/tcp
cd /workspace/avinash/sophia/agent-starter-react
nohup npm start -- --port 3000 --hostname 0.0.0.0 > /workspace/avinash/sophia/frontend.log 2>&1 &
disown

# Restart docker stack (full down/up — restart alone won't reload env_file changes)
cd /workspace/avinash/sophia
docker compose down
docker compose up -d
```

### `echo >>` joined two lines because file had no trailing newline

If a file's last line lacks a trailing newline (`\n`), `echo "newvalue" >> file` will concatenate the newvalue onto the existing last line instead of starting a new one. We hit this on `.gitignore` when both Mac and EC2 appended different lines — EC2's first append joined `READ_ME_NOW.md` and `frontend.log` into the single token `READ_ME_NOW.mdfrontend.log`. The merge conflict on pull then surfaced the joined line.

Safe pattern when appending:

```bash
# Ensure a trailing newline exists BEFORE appending
[ -z "$(tail -c1 path/to/file)" ] || echo >> path/to/file
echo "new entry" >> path/to/file
```

Or just edit with `nano` / your IDE which always normalizes the trailing newline. Avoid raw `echo >>` for files you didn't write yourself.

### Adding a new gitignored file pattern but the `.example` template gets caught too

When you add a gitignore rule like `.env*` or `.env.*` to ignore a secret file, the same rule will ALSO catch any `.env.something.example` template files that document its schema. Two ways out:

1. Add an explicit negation pattern below it: `!.env.*.example`. This is what we did in `sophia-agent/.gitignore` and `agent-starter-react/.gitignore`.
2. Name the template file something that doesn't match the ignore rule (e.g. `env.production.template` instead of `.env.production.example`). Uglier.

Verify with `git check-ignore -v <file>` — that command tells you which line in which `.gitignore` is matching, OR (if negated) which `!` rule is letting it through.

---

## Quick-reference for the common future case

You edited code on EC2 for a demo. Now you want it back on local + GitHub.

```bash
# On EC2:
git status                              # see what's dirty
git diff <unexpected files>             # triage
git checkout -- <noise files>           # discard auto-format
git add <intentional files>
git commit -m "<focused message>"
git push origin main

# On Mac:
git pull origin main
git log --oneline -3                    # verify the EC2 commit is here
```

If LOCAL also has dirty work to push, do that next:

```bash
# On Mac:
git status
git add <files>
git commit -m "<focused message>"
git push origin main

# On EC2:
git pull origin main
```

---

## Cross-references

- `mvp_deployment_shared_ec2.md` — the operational runbook for the shared EC2 itself. Day-to-day cold/warm start, documented problems, glasses repointing.
- `git_setup.md` — the original git + LFS setup. Phase A backend, Phase B Unity, LFS appendix, gotchas. Read this if you're setting up a NEW machine, not for syncing.
- `production_deployment.md` — the future real-production migration plan. Section 0 calls out what changes from MVP to production.
- `deploy_to_ec2.md` — the original deployment sequence (less battle-tested than the MVP doc; the MVP doc supersedes it for shared-EC2 work).

---

## When to update this file

- A new file family enters the project (e.g. `sophia-monitor/` for observability). Add it to the "Where each kind of file belongs" table.
- A new untracked-file class appears that isn't in STEP 2B's list. Add it.
- The deploy moves off shared EC2 to a dedicated instance. Rewrite the "the three machines" intro.
- A sync went wrong in a new way. Add it to "Watch-fors and recovery paths".
