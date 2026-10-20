"""Check the durable/disposable boundary without touching the VM."""
from pathlib import Path
import unittest

import yaml


class HybridStorageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.config = yaml.safe_load((self.root / 'docker-compose.hybrid.yml').read_text())

    def test_durable_volumes(self):
        for name, folder in [('redis-data', 'redis'), ('chatterbox-voices', 'voices'), ('caddy-data', 'caddy')]:
            options = self.config['volumes'][name]['driver_opts']
            self.assertEqual(options['o'], 'bind')
            self.assertIn('/var/lib/ar-voice-agent', options['device'])
            self.assertTrue(options['device'].endswith('/' + folder))

    def test_model_caches_are_disposable(self):
        for name in ('model-cache', 'piper-models'):
            self.assertIn('/mnt/ar-voice-cache', self.config['volumes'][name]['driver_opts']['device'])

    def test_logs_are_bounded(self):
        for service in self.config['services'].values():
            self.assertEqual(service['logging']['options']['max-size'], '10m')
            self.assertEqual(service['logging']['options']['max-file'], '3')

    def test_recovery_does_not_delete_data(self):
        script = (self.root / 'recover-hybrid.sh').read_text()
        self.assertNotIn('down --volumes', script)
        self.assertNotIn('rm -rf', script)
        self.assertIn('flock -n', script)
        self.assertIn('mountpoint -q /mnt', script)

    def test_vllm_cache_flag_matches_pinned_release(self):
        base = yaml.safe_load((self.root / 'docker-compose.yml').read_text())
        self.assertIn('--kv-cache-memory-bytes=2147483648', base['services']['vllm']['command'])

    def test_t4_sampler_fallback(self):
        self.assertIn('VLLM_USE_FLASHINFER_SAMPLER=0', self.config['services']['vllm']['environment'])

    def test_recovery_trigger_waits_for_cloud_init_without_target_cycle(self):
        service = (self.root / 'voice-agent.service').read_text()
        timer = (self.root / 'voice-agent-recovery.timer').read_text()
        self.assertIn('After=cloud-final.service', service)
        self.assertIn('Requires=docker.service hybrid-storage.service', service)
        self.assertNotIn('WantedBy=multi-user.target', service)
        self.assertIn('OnBootSec=90s', timer)
        self.assertIn('OnCalendar=*-*-* *:*:00', timer)
        self.assertIn('Unit=voice-agent.service', timer)


if __name__ == '__main__':
    unittest.main()
