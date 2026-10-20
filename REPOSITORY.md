# Repository workflow and cleanup record

## One working repository

Use `C:\Users\karthikeyan\Desktop\ar-hosted-calling` for development.
Its remote is `https://github.com/TekEssence/ar-hosted-calling.git`.
`main` is the shared baseline; local `karthi` holds the recovered development work.

On 2026-10-20, this standalone repository was copied from
`C:\Users\karthikeyan\Desktop\Calling Bot\ar-hosted-calling`, including its Git
history and uncommitted source changes. Both original repositories under
`Calling Bot` were left untouched as local recovery copies. Do not keep editing
those copies or deploy from them. They contain local configuration and potentially
historical secrets; do not publish or share them as an archive.

The outer repository's `karthi` commit `28c4d61` is **not** a pipeline feature
commit to merge: it removes the project files and replaces them with a nested
repository gitlink. The actual pipeline modules and tests were preserved from
the inner working directory instead. No history was reset or rewritten.

Generated caches, Node dependencies and build output were not copied. Previously
tracked caches, `.DS_Store`, TypeScript build metadata and local environment files
are removed from tracking. Local environment files remain on disk. SSH private
keys were not copied; keep them outside the active repository.

## Daily development

```bash
git status
python -m unittest discover -s tests -p 'test_*.py'
git diff
git add <reviewed-files>
git diff --cached
git commit -m "Describe the change"
```

Before publishing, review the recovered changes and rotate any credentials that
were committed historically. A clean working tree is not proof of secret-free
history. `.env` existed in prior commits; ignoring or untracking it now does not
erase those commits. Review `frontend/.env.local` history too. Any history rewrite
must be separately planned with collaborators; do not force-push as routine cleanup.

When ready to publish, use a reviewed feature branch/PR to `main`. This cleanup
does not push changes or change the remote branches.

## Existing VM: deploy explicitly, not during cleanup

The VM at `85.211.177.112` uses `/opt/ar-voice-agent/deploy` and receives copied
files without `.git`. It therefore has no checked-out Git branch.

The read-only check on 2026-10-20 found:

- Running build commit and time both reported `unknown`.
- `prompts.py`, `docker-compose.yml` and `recover-hybrid.sh` on the VM matched
  the recovered working copy exactly.
- The running backend's `prompts.py` matched that copy too.
- `call_session.py` differed from the recovered working copy even after line-ending
  normalization. The VM file matched the running backend's file.

Local source changes are intentionally retained; no VM files were overwritten or
imported during cleanup. This is a recovered development snapshot, **not** a claim
that all its files are currently deployed.

For a later, approved deployment from Bash/WSL, with SSH/rsync installed:

```bash
# Commit and review changes first. Supply a private key stored OUTSIDE the repo.
export SSH_KEY="$HOME/.ssh/your-vm-key.pem"
bash ./sync.sh azureuser@85.211.177.112
```

Read `OPERATIONS.md` first. `sync.sh` preserves the VM `.env`, rebuilds images and
prints the running commit/time. Cross-check these against the local commit after
deployment. Its commit stamp alone cannot identify uncommitted/untracked changes,
so deploy only a reviewed, clean working tree. This does not record a branch name.

Do not use `deploy_to_vm.sh`, `fix_and_deploy.sh`, bootstrap/fix scripts or the
infrastructure `deploy.sh` for routine updates to this existing hybrid VM. They
are retained for historical context, not validated as the current deployment path;
some contain obsolete local paths or can overwrite host-specific configuration.
Do not run `docker compose restart` to deploy source changes: it reuses old images.
