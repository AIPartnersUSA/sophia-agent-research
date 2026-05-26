# Git setup for the Sophia project

One-time setup to put the whole project in a GitHub remote and adopt a pull/push workflow from here on. Two phases: backend first (clean and small), Unity client later (needs Git LFS for FFI binaries).

---

## Decisions to make first

### Repository host

Recommend **GitHub Private repo**. Most familiar, free for private use, integrates with everything. Alternatives: GitLab (free private), AWS CodeCommit (lives in your AWS account, lower friction with EC2 deploy but worse local tooling). Stick with GitHub unless you have a strong reason.

### Monorepo vs multiple repos

Recommend **monorepo** (this whole directory as one repo). Reasons:
- Research notes (`*.md`) and code (`sophia-agent/`, `agent-starter-react/`, `sophia-glasses/`) cross-reference each other constantly.
- One commit can span backend + frontend + spec doc.
- Easy to clone on the EC2 instance with a single `git clone` for deployment.
- Backend is small (< 100 MB without Unity); Unity adds size but we'll defer that.

Split into multiple repos only if the team grows past 3-4 people working in parallel, or if any subproject needs independent open-sourcing.

### Two-phase plan

**Phase A — NOW (today, 10 minutes):** push everything EXCEPT the Unity client (`sophia-glasses/unity/`) and the reference clones. Backend + frontend + research docs + the Unity scripts themselves (but not the giant Library / packages cache / FFI binaries). This is what you actually need versioned to deploy to EC2.

**Phase B — LATER (1-2 hours when you want it):** add the Unity client with Git LFS for the FFI binaries (~150 MB of platform-specific Rust shared libraries). Worth doing once the backend deploy is stable.

---

## Phase A — push the backend now

### Step 1 — Create the GitHub repo

In a browser:
1. github.com -> New Repository
2. Name: `sophia-agent-research` (or whatever you prefer)
3. Visibility: **Private**
4. **Do NOT** initialize with README / .gitignore / license (we'll push existing content)
5. Create

GitHub will show you commands. Copy the SSH URL (looks like `git@github.com:<you>/sophia-agent-research.git`). If you don't have SSH auth set up yet, use HTTPS for now and switch later.

### Step 2 — Set up the root .gitignore

Create `.gitignore` at the project root with everything to exclude. The file below is comprehensive and accounts for every subproject.

```gitignore
# ============================================================
# macOS / IDE
# ============================================================
.DS_Store
*.swp
*.swo
.vscode/
.idea/

# ============================================================
# Secrets (never commit)
# ============================================================
**/.env
**/.env.local
**/.env.production

# ============================================================
# sophia-agent (Python + uv)
# ============================================================
sophia-agent/.venv/
sophia-agent/.ruff_cache/
sophia-agent/__pycache__/
sophia-agent/**/__pycache__/
sophia-agent/**/*.pyc
sophia-agent/src/sophia_agent.egg-info/
sophia-agent/.pytest_cache/

# uv.lock IS tracked (pin deps reproducibly)
# Same for my-agent
my-agent/.venv/
my-agent/.ruff_cache/
my-agent/__pycache__/
my-agent/**/__pycache__/
my-agent/**/*.pyc
my-agent/src/*.egg-info/

# ============================================================
# agent-starter-react (Next.js)
# ============================================================
agent-starter-react/node_modules/
agent-starter-react/.next/
agent-starter-react/out/
agent-starter-react/build/
agent-starter-react/.turbo/
agent-starter-react/*.tsbuildinfo
agent-starter-react/coverage/

# package-lock.json IS tracked (pin deps reproducibly)

# ============================================================
# Unity client (Phase A skips this entirely)
# Remove or relax these in Phase B
# ============================================================
sophia-glasses/unity/
sophia-glasses/client-sdk-unity/

# ============================================================
# Reference clones (read-only, not our code)
# ============================================================
livekit-agents/
livekit-cli-src/
livekit-server-src/

# ============================================================
# Large media (track manually with LFS if needed)
# ============================================================
videos/
*.mp4
*.mov
*.heic
*.HEIC

# ============================================================
# Temporary local-only docs (delete-after-issue-resolved style)
# ============================================================
READ_ME_NOW.md
```

### Step 3 — Verify before the first push

```bash
cd "/Users/avinashbolleddula/Documents/sophia Agent Research"
git init
git add .gitignore
git status                          # confirm gitignore is the only staged file
git add -A
git status | head -40               # what's about to be committed
```

Scan the `git status` output. Anything you didn't expect to be there? Anything missing that should be there? Common things to double-check:
- `sophia-agent/.env.local` should NOT appear (gitignore working)
- `sophia-agent/uv.lock` SHOULD appear (deps pinned)
- `sophia-glasses/unity/...` should NOT appear (Phase A skip)
- The five Unity scripts at `sophia-glasses/unity/Assets/Scripts/*.cs` will also be skipped — that's OK for Phase A.

If you want the Unity scripts in Phase A even without the full project, you can relax the gitignore one line:
```gitignore
sophia-glasses/unity/
!sophia-glasses/unity/Assets/Scripts/
```
But it's cleaner to defer all of Unity to Phase B as a clean cut.

### Step 4 — First commit and push

```bash
git config user.email "your-email@example.com"     # if not set globally
git config user.name "Your Name"
git commit -m "Initial commit: backend + research docs"
git branch -M main
git remote add origin git@github.com:<your-user>/sophia-agent-research.git
git push -u origin main
```

If the SSH push fails with "Permission denied (publickey)", switch to HTTPS:
```bash
git remote set-url origin https://github.com/<your-user>/sophia-agent-research.git
git push -u origin main             # will prompt for username + Personal Access Token
```

GitHub no longer accepts password auth — for HTTPS you need a Personal Access Token (Settings -> Developer settings -> Personal access tokens -> Generate). Save it in macOS Keychain so you only enter it once.

### Step 5 — Verify the push

Open the repo URL in browser. You should see:
- `sophia-agent/` with src/agent.py, src/token_mint.py, infra/, etc.
- `agent-starter-react/` with components/, app/, package.json
- All the *.md research files at the root
- `.gitignore` you just wrote
- NO `.env.local` files (sensitive)
- NO `node_modules` (huge)
- NO `sophia-glasses/unity/Library` (huge)

Repo size should be < 50 MB after this initial push.

---

## Phase B — add the Unity client later

Defer until backend is stable. When ready:

### Why this needs separate setup

`sophia-glasses/unity/` contains Unity-generated folders that are either huge (Library ~5 GB rebuilt from source) or contain build artifacts that don't need versioning (Logs, Temp, obj). It also depends on `sophia-glasses/client-sdk-unity/` (the local-disk-installed LiveKit Unity SDK) which contains FFI binaries up to 50 MB each. Standard git is bad at large binaries; we use **Git LFS** for those.

### Setup

```bash
brew install git-lfs                 # macOS
git lfs install                      # set up LFS hooks in this repo
```

Add to `.gitattributes` at the project root:
```
sophia-glasses/client-sdk-unity/Runtime/Plugins/** filter=lfs diff=lfs merge=lfs -text
*.aar filter=lfs diff=lfs merge=lfs -text
*.dll filter=lfs diff=lfs merge=lfs -text
*.so filter=lfs diff=lfs merge=lfs -text
*.dylib filter=lfs diff=lfs merge=lfs -text
*.framework/** filter=lfs diff=lfs merge=lfs -text
*.apk filter=lfs diff=lfs merge=lfs -text
```

Replace the Unity exclusions in `.gitignore` with Unity-specific ones that keep what matters and drop what doesn't:

```gitignore
# Unity client (Phase B)
# Keep: Assets/, Packages/, ProjectSettings/
# Drop: Library/, Temp/, Logs/, obj/, UserSettings/, Build/, .vs/
sophia-glasses/unity/Library/
sophia-glasses/unity/Temp/
sophia-glasses/unity/Logs/
sophia-glasses/unity/obj/
sophia-glasses/unity/UserSettings/
sophia-glasses/unity/Build/
sophia-glasses/unity/Builds/
sophia-glasses/unity/.vs/
sophia-glasses/unity/*.csproj
sophia-glasses/unity/*.sln

# Unity build output - track via LFS if you want, otherwise drop
sophia-glasses/unity/sophia-glasses.apk
```

Then:
```bash
git add .gitattributes .gitignore
git add sophia-glasses/
git commit -m "Add Unity client with Git LFS for FFI binaries"
git push
```

First push will be slow because LFS uploads the binaries.

### Beware: Packages/manifest.json has a local-disk path

```json
"com.xreal.xr": "file:/Users/avinashbolleddula/Downloads/package",
"io.livekit.livekit-sdk": "file:/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/client-sdk-unity",
```

The LiveKit path becomes valid for anyone who clones the repo (since client-sdk-unity is now in the repo). The XREAL one will break on every other machine. Two fixes:

A. Vendor the XREAL package too: copy `~/Downloads/package` into `sophia-glasses/xreal-sdk/` and change the manifest to `file:./../xreal-sdk`. Add the folder to LFS for any AARs inside.

B. Document the XREAL install step as a manual prerequisite in `sophia-glasses/README.md` and have the user point the manifest at their own local path post-clone.

Option A is cleaner for team reproducibility; Option B is fine for a one-person project.

---

## Workflow from now on

### Daily push pattern

You make a change locally. To push it:

```bash
cd "/Users/avinashbolleddula/Documents/sophia Agent Research"
git status                          # see what changed
git diff                            # review the diffs
git add -A                          # stage everything
git commit -m "concise message"     # commit
git push                            # push to GitHub
```

For meaningful commit messages, follow the same pattern existing entries use:
```
Add SophiaSpeaker child GameObject per remote track (Q58)
Fix sample-rate trap on Mac Editor: macOS Audio MIDI Setup required (Q52)
Patch agent-starter-react to honor ?room= URL param for shared-session demo (Q56)
```

### Pulling on a new machine

```bash
git clone git@github.com:<you>/sophia-agent-research.git
cd sophia-agent-research

# sophia-agent setup
cd sophia-agent
cp .env.example .env.local          # then edit .env.local with real values
uv sync                             # install Python deps
cd ..

# agent-starter-react setup
cd agent-starter-react
cp .env.example .env.local 2>/dev/null || true
# manually create .env.local with LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
npm install
cd ..

# Phase B only: open sophia-glasses/unity/ in Unity Hub
```

### Branches

For a one-person project starting out, keep it simple:
- `main` is what runs in production (eventually).
- New work happens on `main` directly until the project stabilizes.

Once you start deploying continuously or other people contribute, adopt feature branches:
- `main` is protected, only updates via PR
- `feat/<topic>` branches for new work
- `fix/<topic>` branches for bugs
- PR -> review -> merge to main
- Tags like `v0.1.0`, `v0.2.0` for releases

### What goes in PR descriptions

Reference the Q-number from `livekit_doubts.md` or `livekit_deployment.md` if the change relates to a documented issue. Cross-link the spec file (e.g. `HUD_direction_a.md` for UI changes).

### What NOT to commit ever

- `.env.local` (already in gitignore, but always double-check `git status` before commit)
- AWS credentials, API keys, JWT secrets
- Beam Pro device serial numbers, Tailscale tokens
- Personal information

If a secret leaks accidentally, **rotate it immediately** (don't just delete the commit — Git history persists). Generate a new LIVEKIT_API_SECRET, push to Secrets Manager, redeploy.

---

## What this repo will look like

Top-level structure after Phase A push:

```
sophia-agent-research/
├── .gitignore
├── CLAUDE.md                         <- AI assistant orientation
├── README.md (you should add one)
├── git_setup.md                      <- this file
├── production_deployment.md          <- next file we're writing
├── steps_to_run.md
├── demo_multiroom_recording.md
├── unity_approach.md
├── livekit_doubts.md
├── livekit_deployment.md
├── COMPARISON.md
├── STT_models.md
├── TTS_models.md
├── STS_models.md
├── sophia_pipeline_presentation.html
├── sophia_week2_presentation.html
├── *.py                              <- inference-server.py and friends (reference)
├── sophia-agent/                     <- main agent backend (Python)
├── agent-starter-react/              <- React frontend (Next.js)
├── my-agent/                         <- benchmark agent (untouched)
└── sophia-glasses/                   <- Phase B will add this
```

Once Phase B lands, also:
```
└── sophia-glasses/
    ├── README.md
    ├── AGENTS.md
    ├── HUD_direction_a.md
    ├── READING_GUIDE.md
    ├── unity/
    │   ├── Assets/
    │   ├── Packages/
    │   └── ProjectSettings/
    └── client-sdk-unity/             <- vendored LiveKit Unity SDK (LFS)
```

---

## Quick reference

| Task | Command |
|---|---|
| Initial setup | See Phase A Step 4 |
| Daily push | `git status && git add -A && git commit -m "..." && git push` |
| Pull latest before starting work | `git pull` |
| Undo uncommitted changes to a file | `git checkout -- <file>` |
| See what would be pushed | `git log origin/main..HEAD` |
| See remote URL | `git remote -v` |
| Switch from HTTPS to SSH later | `git remote set-url origin git@github.com:<you>/<repo>.git` |

---

## What to do RIGHT NOW

1. Create the GitHub repo (private, blank).
2. Copy the .gitignore content from Step 2 above into a new `.gitignore` file at the project root.
3. Run the commands in Step 3 + 4 above.
4. Verify the push in browser per Step 5.

Total time: 10-15 minutes. Then read `production_deployment.md` for the EC2 deploy plan.
