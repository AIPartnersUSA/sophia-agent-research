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

---

## Gotchas we actually hit (2026-05-25 setup session)

The setup wasn't all-smooth. Two gotchas worth knowing about so future-you doesn't waste an hour rediscovering them.

### Gotcha 1: the submodule trap when a folder has its own .git/

What happened: `agent-starter-react/` and `sophia-glasses/client-sdk-unity/` were both originally cloned from upstream repos, so each had its own `.git/` directory inside. When we ran `git add agent-starter-react/` at the outer project root, git noticed the inner `.git` and recorded only a "gitlink" (a 40-character commit SHA pointing into the other repo's history). It did NOT actually stage the files. The first push to GitHub uploaded a gitlink entry — anyone cloning got an EMPTY `agent-starter-react/` folder with no source code, and no `.gitmodules` to tell them where to find it.

How we found it: `git status` showed `modified: agent-starter-react (modified content, untracked content)` with submodule wording. `git ls-tree HEAD agent-starter-react` returned `160000 commit <sha>	agent-starter-react` — mode 160000 is the gitlink mode. Source files were nowhere on the remote.

How to fix:
```bash
# 1. Remove the inner .git directories (severs the submodule link).
rm -rf agent-starter-react/.git
rm -rf sophia-glasses/client-sdk-unity/.git

# 2. Tell the outer repo to forget the gitlink entries.
git rm --cached agent-starter-react
git rm --cached sophia-glasses/client-sdk-unity

# 3. Re-stage everything inside as regular files.
git add agent-starter-react/
git add sophia-glasses/client-sdk-unity/

# 4. Verify LFS is catching binaries.
git lfs ls-files | grep client-sdk-unity | head

# 5. Commit and push.
git commit -m "Vendor agent-starter-react and client-sdk-unity as files (not submodules)"
git push
```

This is destructive in the sense that you lose the inner subproject's git history (you can no longer `git log` the upstream commits of agent-starter-react inside the outer repo). The WORKING TREE files are preserved, including any local edits.

How to prevent it next time: BEFORE `git add`-ing a directory that came from a clone, run `find <dir> -name .git -type d` and remove any inner `.git/` directories first. Or use `git submodule add` if you genuinely want it as a submodule (different workflow, requires a `.gitmodules` file).

### Gotcha 2: macOS Privacy & Security blocks Terminal from ~/Downloads

What happened: We tried `cp -R ~/Downloads/package <repo>/sophia-glasses/xreal-sdk` and got `cp: /Users/.../Downloads/package: Operation not permitted`. Same `ls -la ~/Downloads/` failed with "Operation not permitted" — even though Finder could see the folder fine.

Cause: macOS Sequoia (and recent Sonoma) treats `~/Downloads/`, `~/Documents/`, `~/Desktop/` as protected folders. Apps need explicit "Files and Folders" or "Full Disk Access" permission to read from them. Terminal.app doesn't have this by default. Same applies to any subprocess Terminal launches (`cp`, `ls`, `git`, etc.).

How to fix (one-time setup):
1. Apple menu > System Settings > Privacy & Security > Full Disk Access.
2. Click +, navigate to Applications > Utilities > Terminal, add it.
3. Quit Terminal completely (Cmd+Q, not just close window) and reopen.

After that, Terminal can read all of `~/Downloads/`, `~/Documents/`, etc. without prompting.

Workaround if you don't want to grant Full Disk Access: do the file copy in Finder (drag-and-drop or Copy/Paste). Finder is allowed by default. This is what we did for the XREAL SDK copy.

How this manifests in Claude Code: my Bash tool inherits the parent Terminal's permissions, so when Terminal doesn't have Full Disk Access, I see "Operation not permitted" too. I was confused for a couple turns thinking the source folder was actually empty.

---

## Git LFS + SDK vendoring — concepts

Discussion captured 2026-05-29 while prepping the Week 3 presentation. Worth keeping for anyone who wonders "what's this LFS thing and why did we set it up this way."

### Q1. What is Git LFS?

Git Large File Storage extension. Solves a known git weakness: binary files.

Git tracks file history by computing diffs between versions. For text files (code, docs), diffs are small and efficient — committing a one-line change to a 10 MB source file adds maybe 100 bytes to git history. For binary files (compiled libraries, AARs, DLLs, images, videos, model weights), there's no meaningful diff — git treats them as "old version" + "totally new version" and stores the ENTIRE new file every commit. That makes binary-heavy repos grow huge fast: a 50 MB DLL committed 10 times = 500 MB in `.git/` history forever, even if you only have one version checked out today.

Git LFS works around this by storing binaries OUTSIDE git's normal history. Tiny pointer files go in git history (~3 lines, ~150 bytes each). Actual binaries live on a separate LFS server (GitHub's LFS storage is typical). A pointer looks like:

```
version https://git-lfs.github.com/spec/v1
oid sha256:abc123...
size 12345678
```

When you push, git uploads the pointer to the git repo AND uploads the binary to the LFS server. When someone clones, they get the pointers immediately (fast, small). When they run `git lfs pull`, LFS downloads the actual binaries based on the pointers.

### Q2. Why did we need LFS for THIS project?

Two reasons, both load-bearing.

**Reason 1: GitHub's hard per-file size limit.** GitHub rejects any single file over 100 MB pushed via regular git. Without LFS, the LiveKit FFI binaries (50-80 MB per platform) and the XREAL AARs would fail to push at all. With LFS the limit goes up to 2 GB per file, which our files comfortably fit under.

**Reason 2: Repo size and clone speed.** We vendored two third-party Unity SDKs into the repo for portability:
- `sophia-glasses/xreal-sdk/` — XREAL SDK 3.1.0, ~243 MB total, 10 AAR files
- `sophia-glasses/client-sdk-unity/` — LiveKit Unity SDK with FFI binaries for every platform (Android arm64/x86, iOS, macOS arm64/x86, Linux, Windows)

Without LFS, every fresh clone would download all 300+ MB of binaries, the `.git/` folder would balloon with each binary commit, and history scrolling would be slow. With LFS, fresh clones are fast (only pointers download). Anyone wanting to build the Unity project runs `git lfs pull` once.

136 files in our repo are tracked via LFS as of 2026-05-28.

### Q3. With vs without LFS — what changes?

**Without LFS:**
- Approach A: SDKs live on local machines, referenced via local-only paths in manifests (the original `~/Downloads/package` problem). Project literally won't build on any other machine without setting up those exact local files.
- Approach B: Put SDKs directly in git. Hits the 100 MB file-size limit AND bloats the repo history forever. Push fails for large files. Clones get slow.

**With LFS:**
- SDKs are "in the repo" from the user's perspective. Git history stays small (only pointers). Real binaries live on a separate LFS server. Anyone clones + runs `git lfs pull` = fully buildable project.

### Q4. What if upstream SDKs (XREAL, LiveKit) release new versions? Do we auto-update?

NO. Vendored SDKs are SNAPSHOTS. We have whatever version we copied in at vendoring time. Upstream updates don't flow into our repo automatically.

To upgrade an SDK someone has to:
1. Download the new SDK version from XREAL's developer portal / LiveKit's GitHub releases.
2. Replace the entire contents of `sophia-glasses/xreal-sdk/` or `client-sdk-unity/` with the new files.
3. Commit + push. LFS handles the new binaries automatically.
4. Test the Unity project still builds and the voice loop still works (since SDK upgrades can break API contracts — our wrapper code in `SophiaConnection.cs` calls SDK APIs that might have changed).
5. Everyone else on the team pulls + runs `git lfs pull` to get the new version.

Step 4 is the important one. Major SDK upgrades often break things. Upgrading isn't free; it needs validation.

**Trade-off of pinning (what we have):** Stable. Predictable. Upstream breaking changes don't surprise us at a bad time (e.g. day of a demo). Build today = build same way next month. But we miss security fixes and new features until we manually upgrade. Easy to forget about and get stale.

### Q5. Is LFS-vendoring what other teams typically do?

Yes, for our situation specifically. Across industry there are 4-5 common approaches; which one fits depends on what the SDK provides.

1. **Package managers (most common when available).** SDK is published to a public registry, you declare a version in a manifest file, the package manager downloads it on demand. Examples: NPM (JavaScript), PyPI (Python), Maven Central (Android/Java), NuGet (.NET), Swift Package Manager / CocoaPods / Carthage (iOS), Unity Package Manager registries (if the SDK provider operates one). We can't use this for XREAL because they distribute via developer-portal download, not a public registry. LiveKit Unity SDK isn't on a Unity Asset Store registry either.

2. **Git LFS vendoring (what we do).** Used when SDKs are distributed as tarballs/zips and not on a package registry, or when you specifically want a pinned in-repo copy. Common in Unity game development, Unreal Engine projects, ML projects with model weights, anything with media assets. Pinned versions, portable to anyone, but you manage upgrades manually.

3. **Git submodules.** Point at another git repo at a specific commit. Each `git submodule update` fetches just that pinned commit. Common in larger orgs with many internal repos. Cons: the "submodule trap" (mode 160000 gitlinks vs files — we hit this earlier in this very project), complex for new team members, breaks if upstream repo is private or deleted.

4. **Build-time download scripts.** A `setup.sh` or `Makefile` rule that downloads SDKs on first build. Lets you keep them entirely out of the repo. Used when: vendor license prohibits redistribution, SDK is too big even for LFS (multiple GB), or every build genuinely needs the latest (rare; usually bad practice).

5. **Native git, no LFS.** Only viable if the SDK is small (under 100 MB per file) and doesn't update often. Header-only C++ libraries, source-only Python deps, small static libraries.

### Q6. Decision tree for "how do I handle SDK X?"

```
Is the SDK published to a public package registry (NPM, PyPI, Maven, UPM, ...)?
├── Yes → Use the registry. Easiest. Declare version in manifest, done.
└── No
    ├── Is the SDK proprietary, distributed via vendor portal?
    │   ├── Yes → Vendor with LFS (our case for XREAL).
    │   └── No
    │       ├── Is it on a public git repo and small (< 100 MB / file)?
    │       │   ├── Yes → Git submodule (with care for the trap) or vendor without LFS.
    │       │   └── No → Build-time download script.
```

For our project: XREAL SDK is via developer portal (no public registry, no public git repo). LiveKit Unity SDK has FFI binaries that push past size limits even though source is on GitHub. Both land in "vendor with LFS" by elimination.

### Q7. What did our actual setup look like?

`.gitattributes` at repo root declares which patterns route through LFS:

```
sophia-glasses/xreal-sdk/**/*.aar     filter=lfs diff=lfs merge=lfs -text
sophia-glasses/xreal-sdk/**/*.dll     filter=lfs diff=lfs merge=lfs -text
sophia-glasses/xreal-sdk/**/*.so      filter=lfs diff=lfs merge=lfs -text
sophia-glasses/xreal-sdk/**/*.dylib   filter=lfs diff=lfs merge=lfs -text
sophia-glasses/xreal-sdk/**/*.bundle  filter=lfs diff=lfs merge=lfs -text
sophia-glasses/xreal-sdk/**/*.a       filter=lfs diff=lfs merge=lfs -text
```

Same block repeated for `sophia-glasses/client-sdk-unity/`. Any file matching these patterns automatically goes through LFS when staged.

Plus a one-time install on each developer machine:
```bash
brew install git-lfs    # macOS
git lfs install         # set up LFS hooks in the local repo
```

After clone:
```bash
git clone <repo>
cd <repo>
git lfs pull            # fetch the actual binaries
```

GitHub free tier: 1 GB LFS storage + 1 GB/month bandwidth. We're well under that with 136 files for our use case.

### Q8. What happens if someone clones without `git lfs pull`?

They get pointer files instead of binaries. Opening such a file shows:

```
version https://git-lfs.github.com/spec/v1
oid sha256:abc123...
size 12345678
```

Three lines of text where they expected a 50 MB DLL. Unity will reject those files at build time with cryptic errors about invalid native libraries.

Diagnostic: if your Unity build complains about missing/corrupt FFI binaries after a fresh clone, check by running `cat sophia-glasses/client-sdk-unity/Runtime/Plugins/ffi-macos-arm64/liblivekit_ffi.dylib | head -3` — if it's three lines of text, run `git lfs pull`.

### Files that capture LFS in our repo

- `.gitattributes` at repo root — declares LFS-tracked file patterns.
- `.gitignore` — does NOT exclude LFS files; LFS still tracks them via the attributes file.
- `git_setup.md` (this file) — Phase B section + this LFS concepts appendix.
- `livekit_doubts.md` Q59 — Unity package vendoring + manifest.json path math gotcha that came up during XREAL SDK vendoring.

---

## Cross-references — git topics that live in other files

Some git workflow lessons surfaced during the EC2 deployment (not the initial git setup) and live in deployment docs. Pointers here so future-you can find them when looking in git_setup.md by habit.

### `mvp_deployment_shared_ec2.md`

- **Section "Git workflow + sync between Mac and EC2"** — daily flow pattern (edit on Mac → commit + push → `git pull` on EC2), explanation of which files are versioned vs not (env files / livekit.prod.yaml / docker-compose.yml are local-only, chmod 600, never committed), the two-commit pattern (code fixes + docs split for cleaner review).

- **Problem 12 — `git pull` on EC2 conflicts with local uncommitted edits.** Pattern: editing the same file via nano on the EC2 AND via the IDE on the Mac independently → `git pull` errors on EC2 because uncommitted local changes would be overwritten. Fix: `git checkout -- <files>` to discard EC2's dirty versions, then `git pull`. Prevention rule: edit ONLY on the Mac going forward.

- **Problem 13 — GitHub push rejected with "write access not granted".** When pushing to a cross-org repo (we hit this with `AIPartnersUSA/aws-infra`). Fix: ask the repo owner to add your GitHub user as a Collaborator with Write role. Branch-level vs repo-level permissions clarification — repo-level Write is what's needed; branch protection rules are a separate concept that doesn't block PR-based workflows.

### `deploy_to_ec2.md`

- **Phase 5 — Cloned repo via SSH.** The exact `git clone git@github.com:...` + `git lfs pull` sequence used on the EC2, including the "trailing dot clones INTO current dir" trick.

- **Phase 4 — SSH key on EC2 + GitHub.** Generating a per-machine SSH key and adding to GitHub, vs reusing your Mac's key (don't — keep machine identities separate).

### `livekit_doubts.md`

- **Q59** — Unity package vendoring with Git LFS + the manifest.json path math gotcha (`file:../../` not `file:../` because Unity resolves `file:` URIs relative to manifest.json location, not project root). Came up when vendoring XREAL SDK + LiveKit Unity SDK.

- **Q60** — Unity 6 TMP API deprecation. Not strictly git, but shows up as a dirty working tree if you edit on EC2 and Mac independently.

### Other notes

- **`.gitignore`** at the repo root has comments explaining each subproject's exclusions. Read it when adding new subprojects.

- **`.gitattributes`** at the repo root declares the LFS patterns for the two vendored Unity SDKs. Add new patterns here if vendoring more binaries.

- Daily workflow assumption: edit on Mac, push to GitHub, pull on EC2. Avoid the Problem-12 pattern by NEVER editing the same file in two places without committing in between.

### `git_sync.md` (added 2026-05-29, validated 2026-06-01)

The operational follow-on to this file. While `git_setup.md` is about getting the repo started, **`git_sync.md` is about reconciling Mac + EC2 + GitHub when they drift** (which happens any time you edit code directly on EC2 during a demo or live session). 8-step procedure with triage rules for unexpected dirty files, secret handling for untracked files, Unity build-artifact cleanup, and recovery paths for push-rejected / pull-overlap scenarios. Read this when `git status` looks confusing on either side.

### `HANDOFF.md` (added 2026-06-01)

The infra-team onboarding doc. Hand a fresh infra engineer this file before they touch anything — it tells them what's in the repo, what's intentionally not in the repo (the gitignored secret files + their schemas), what architecture to preserve (e.g. host networking for the SFU), what they need to build for production (k8s manifests, ArgoCD, real auth, TLS, CI/CD), and 8 anti-patterns to avoid (don't put SFU behind ALB, don't reuse MVP keys, don't `npm install` in container builds — use `npm ci`). The 12-step migration sequence at the bottom is the recommended order.

### `.env.*.example` template files (added 2026-06-01)

Three template files document the schema of the gitignored secret files, with `openssl rand` commands inline:
- `sophia-agent/.env.production.example`
- `sophia-agent/infra/livekit.prod.yaml.example`
- `agent-starter-react/.env.local.example`

For fresh setups, copy each `.example` to its non-example sibling and fill in values. The subfolder `.gitignore` files were patched with `!.env.*.example` negation patterns so the templates stay tracked while the real `.env.*` files stay ignored.
