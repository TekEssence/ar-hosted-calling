"""One-time installer for this VM. Preserves old roots/configuration, no disk purchase."""
import datetime
import json
import os
from pathlib import Path
import pwd
import subprocess


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


app = Path('/opt/ar-voice-agent/deploy')
if os.geteuid() != 0 or Path.cwd() != app:
    raise SystemExit('Run with sudo from /opt/ar-voice-agent/deploy')
user = pwd.getpwnam('azureuser')
if (app / '.hybrid.env').exists():
    raise SystemExit('Hybrid setup already exists; inspect it instead of reinstalling')
if run('docker', 'ps', '-aq').strip() or run('docker', 'volume', 'ls', '-q').strip():
    raise SystemExit('Containers/volumes exist. Back up and migrate their data before installing.')
run('mountpoint', '-q', '/mnt')
fstab = Path('/etc/fstab')
old_fstab = fstab.read_text()
cron = subprocess.run(['crontab', '-u', 'azureuser', '-l'], text=True, capture_output=True)
old_cron = cron.stdout
expected_cron = '@reboot cd /opt/ar-voice-agent/deploy && docker compose --profile prod --profile tls up -d'
system_cron = Path('/etc/cron.d/ar-voice-agent-cron')
if system_cron.exists() and system_cron.read_text().strip() != expected_cron:
    raise SystemExit('Unexpected system cron content; review manually')
for line in old_cron.splitlines():
    if line.startswith('@reboot') and '/opt/ar-voice-agent/deploy' in line and line != expected_cron:
        raise SystemExit('Unexpected app reboot entry; review manually')
backup = Path('/home/azureuser/hybrid-config-backups') / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup.mkdir(parents=True, mode=0o700)
os.chmod(backup.parent, 0o700)
os.chown(backup.parent, user.pw_uid, user.pw_gid)
os.chown(backup, user.pw_uid, user.pw_gid)
for name in ('/etc/fstab', '/etc/docker/daemon.json', '/etc/containerd/config.toml', '/etc/cron.d/ar-voice-agent-cron'):
    path = Path(name)
    if path.exists():
        target = backup / name.lstrip('/').replace('/', '__')
        target.write_bytes(path.read_bytes())
        os.chmod(target, 0o600)
(backup / 'azureuser.crontab').write_text(old_cron)
os.chmod(backup / 'azureuser.crontab', 0o600)
print(f'Configuration backup: {backup}', flush=True)
# No live application containers exist; stop runtime sockets before changing roots.
run('systemctl', 'stop', 'docker.service', 'docker.socket', 'containerd.service')
lines = []
for line in old_fstab.splitlines():
    fields = line.split()
    if fields[:2] == ['/mnt/containerd', '/var/lib/containerd']:
        continue
    if fields[:2] == ['/dev/disk/cloud/azure_resource-part1', '/mnt']:
        fields[3] = ','.join(part for part in fields[3].split(',') if part != '_netdev')
        line = '\t'.join(fields)
    lines.append(line)
fstab.write_text('\n'.join(lines) + '\n')
daemon_path = Path('/etc/docker/daemon.json')
daemon = json.loads(daemon_path.read_text())
daemon.update({'data-root': '/mnt/docker-hybrid', 'storage-driver': 'overlay2',
               'log-driver': 'json-file', 'log-opts': {'max-size': '10m', 'max-file': '3'}})
daemon.setdefault('features', {})['containerd-snapshotter'] = False
daemon_path.write_text(json.dumps(daemon, indent=2) + '\n')
run('dockerd', '--validate', '--config-file=/etc/docker/daemon.json')
containerd_path = Path('/etc/containerd/config.toml')
old_config = containerd_path.read_text()
import re
new_config = re.sub(r'(?m)^\s*root\s*=.*\n?', '', old_config)
containerd_path.write_text('root = "/mnt/containerd-hybrid"\n' + new_config)
for service in ('docker', 'containerd'):
    folder = Path(f'/etc/systemd/system/{service}.service.d')
    folder.mkdir(exist_ok=True)
    path = folder / 'ar-voice-hybrid.conf'
    if path.exists():
        raise SystemExit(f'Existing hybrid drop-in: {path}')
    path.write_text('[Unit]\nRequires=hybrid-storage.service\nAfter=hybrid-storage.service\n')
run('install', '-m', '644', str(app / 'hybrid-storage.service'), '/etc/systemd/system/hybrid-storage.service')
run('install', '-m', '644', str(app / 'voice-agent.service'), '/etc/systemd/system/voice-agent.service')
run('install', '-m', '644', str(app / 'voice-agent-recovery.timer'), '/etc/systemd/system/voice-agent-recovery.timer')
env = app / '.hybrid.env'
env.write_text('PERSISTENT_DATA_DIR=/var/lib/ar-voice-agent\nTEMP_CACHE_DIR=/mnt/ar-voice-cache\nCOMPOSE_PROJECT_NAME=ar-voice-agent\nCOMPOSE_FILE=docker-compose.yml:docker-compose.hybrid.yml\n')
os.chmod(env, 0o600)
os.chown(env, user.pw_uid, user.pw_gid)
os.chmod(app / '.env', 0o600)
os.chmod(app, 0o750)
new_cron = '\n'.join(line for line in old_cron.splitlines() if line != expected_cron)
if new_cron != old_cron.rstrip('\n'):
    subprocess.run(['crontab', '-u', 'azureuser', '-'], input=new_cron + '\n', text=True, check=True)
if system_cron.exists():
    system_cron.rename(backup / 'disabled-system-cron')
run('systemctl', 'daemon-reload')
run('systemctl', 'enable', 'hybrid-storage.service', 'voice-agent-recovery.timer')
run('systemctl', 'disable', 'voice-agent.service')
run('systemctl', 'start', 'hybrid-storage.service', 'containerd.service', 'docker.service')
print('Storage/runtime configured; old Docker root preserved. Start voice-agent-recovery.timer to recover.', flush=True)
