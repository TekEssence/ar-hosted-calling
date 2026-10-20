# Development VM: hybrid recovery

## Storage layout

No new Azure resource is required. The current voice-calling architecture remains
Next.js + Caddy + FastAPI + Redis + vLLM + the existing TTS services. Opik and
automatic deallocation are not reconfigured.

Permanent OS disk:
- `/opt/ar-voice-agent/deploy`: code, VM `.env`, recovery scripts and image lock.
- `/var/lib/ar-voice-agent/redis`: database and settings.
- `/var/lib/ar-voice-agent/voices`: uploaded voice reference files.
- `/var/lib/ar-voice-agent/caddy`: HTTPS certificates.
- `$HOME/ar-voice-agent-backups`: small Redis RDB snapshots by default.

Azure temporary resource disk (may be erased on deallocation):
- `/mnt/docker-hybrid`: overlay2 images, writable container layers and build cache.
- `/mnt/containerd-hybrid`: containerd disposable data.
- `/mnt/ar-voice-cache/models`: downloadable model caches.
- `/mnt/ar-voice-cache/piper`: downloadable Piper voice model.

`docker-compose.hybrid.yml` binds named volumes to these explicit host folders.
Losing Docker's volume metadata does not erase the permanent folders. Recovery
recreates the volume definitions. Existing lost data requires an existing backup;
this implementation cannot restore it from nothing.

## Boot and recovery

1. Azure/cloud-init prepares the resource disk.
2. `hybrid-storage.service` verifies `/mnt` is the Azure resource partition and
   creates folders before Docker/containerd start.
3. `voice-agent-recovery.timer` triggers recovery after 90 seconds of uptime and
   checks every minute for an inactive service. `voice-agent.service` waits for
   `cloud-final.service`, then calls `start.sh`, which detects `.hybrid.env` and
   runs `recover-hybrid.sh` under the `azureuser` account. The application service
   is NOT enabled under multi-user.target (cloud-final runs after that target).
   An active recovery job or successfully active service is not started again.
4. Recovery verifies mounts, Docker root/driver, durable folders and free space.
5. `pin-hybrid-images.py` resolves explicit upstream references to immutable
   registry digests once, stored in permanent `.hybrid-images.env`. vLLM starts
   from v0.11.0. FlashInfer sampling is disabled for the T4 because its bundled
   sampler JIT crashes on SM75; vLLM uses its supported PyTorch-native sampler.
6. Missing images are downloaded; missing app images are built sequentially.
7. Missing Piper files are downloaded atomically; GPU services download their
   other models into disposable caches during startup.
8. Compose starts the stack and readiness checks wait for frontend, Whisper,
   Redis and the configured vLLM model. Failures are logged and retried by systemd.

First recovery and recovery after disk erasure may take a long time. Internet,
registry, model access, valid credentials and sufficient working space are still
required. Image digests prevent moving image tags but Python/npm dependencies and
model repositories are not fully locked. No claim of zero-error recovery is made.

The service has no fixed build timeout; each failed attempt retries after 30s.
The timer also retries missed boot activation/dependency failures every minute.
To stop retries while investigating:
`sudo systemctl stop voice-agent-recovery.timer voice-agent.service`.
To resume automatic activation: `sudo systemctl start voice-agent-recovery.timer`.
To inspect: `sudo journalctl -u voice-agent -n 100 --no-pager`.
To follow recovery: `sudo journalctl -fu voice-agent`.

## Installation and backup

`install-hybrid.py` is a one-time, VM-specific installer. It refuses existing
containers/volumes rather than discarding their data. Run with sudo from the app
folder after code deployment. It backs up configs/crontab, replaces only the known
project reboot entries, corrects the resource-disk/containerd setup, installs units
and prepares runtimes. It preserves the old `/mnt/docker` root; it does not start
the app until `sudo systemctl start voice-agent-recovery.timer` is run separately.

Before initial deployment, the old app was archived under
`/home/azureuser/hybrid-config-backups/app-before-hybrid-20261012.tar.gz`.
Installer configuration backups are in timestamped folders in the same directory.
These archives contain secrets; their parent directory is restricted. Do not
restore old temporary-storage configuration blindly.

`bash backup-redis.sh` creates a completed RDB snapshot on permanent storage and
keeps seven. SAVE can briefly pause a large development database. Backup copies
are NOT independent of OS-disk loss; copy them to an existing trusted machine.
No paid backup resource or automatic backup schedule was created.

## Development changes

Deploy code without overwriting the VM `.env` or image lock. Run `bash rebuild.sh`
after source changes; recovery reuses existing app images and does not detect
source changes automatically. `rebuild.sh` loads hybrid Compose settings.
Use the `ar-voice-agent` Compose project name to preserve its volume identity.

Do not run legacy bootstrap/fix scripts: they can overwrite the new runtime
configuration. Do not delete permanent folders or `.hybrid-images.env` during
routine cleanup. Removing an image lock deliberately selects new upstream images
and requires compatibility validation again.

## Validation and limits

`python -m unittest discover -s tests -p 'test_*.py'` tests readiness and storage
configuration without loading GPU models. `/health` is liveness; `/ready` checks
core dependencies. A healthy core is not proof of Twilio/TTS/external connectivity.
Validate the public HTTPS UI, `/ready`, voice synthesis, and a real test call.
Deallocate/start testing requires a separate approved interruption; no temporary
disk is deliberately erased during implementation.

Recovery pauses below 1 GiB free permanent space or 10 GiB temporary space.
These are guardrails, not a guarantee that a large build fits. Container logs are
bounded to 3 x 10 MB per container. Database/voices/system logs can still grow;
check `df -h / /mnt`. No unattended image/data pruning is installed.

## Rollout status

The hybrid layout and startup units are installed on the VM. Initial recovery was
completed on 2026-10-12 at 06:23:35 UTC. Public `/ready` returned healthy Whisper,
Redis and LLM checks. `validate-hybrid.py` tests the public UI, local LLM generation,
Piper audio and permanent volume mappings without making a phone call. Restart-cycle
validation succeeded at 06:37:21 UTC. A subsequent deallocate/start erased `/mnt`
and exposed a missed boot activation: permanent data survived, but recovery was
not invoked. A delayed/repeating timer and explicit cloud-final ordering were
installed, and cold recovery was started. Completion and a further automatic
deallocate/start test must be confirmed from execution. Twilio calls are untested.
