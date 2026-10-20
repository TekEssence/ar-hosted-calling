"""Resolve Docker Hub references once; atomic durable lock survives resource-disk loss."""
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

lock = Path(__file__).resolve().with_name('.hybrid-images.env')
if not lock.exists():
    images = {
        # Explicit release rather than a moving latest tag; validate on the T4.
        'VLLM_IMAGE': ('vllm/vllm-openai', 'v0.11.0'),
        'REDIS_IMAGE': ('library/redis', '7-alpine'),
        'CADDY_IMAGE': ('library/caddy', '2-alpine'),
        'PYTORCH_IMAGE': ('pytorch/pytorch', '2.5.1-cuda12.4-cudnn9-runtime'),
        'NODE_IMAGE': ('library/node', '20-alpine'),
    }
    lines = []
    for key, (repo, tag) in images.items():
        query = urllib.parse.urlencode({'service': 'registry.docker.io', 'scope': f'repository:{repo}:pull'})
        with urllib.request.urlopen('https://auth.docker.io/token?' + query, timeout=30) as response:
            token = json.load(response)['token']
        request = urllib.request.Request(f'https://registry-1.docker.io/v2/{repo}/manifests/{tag}', headers={
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json',
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            digest = response.headers['Docker-Content-Digest']
        if not digest or not digest.startswith('sha256:'):
            raise RuntimeError(f'Missing registry digest for {repo}')
        lines.append(f'{key}={repo}@{digest}\n')
    temporary = lock.with_suffix('.partial')
    temporary.write_text(''.join(lines), encoding='utf-8')
    os.chmod(temporary, 0o600)
    temporary.replace(lock)
    print('Pinned registry images; runtime compatibility still requires validation.')
