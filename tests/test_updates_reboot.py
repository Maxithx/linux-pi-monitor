import unittest
from unittest.mock import Mock, patch

from flask import Flask

from routes.updates import updates_bp
from routes.updates import views_updates


class UpdatesRebootSimulationTests(unittest.TestCase):
    """Exercise the update-page reboot flow without contacting a real host."""

    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="test")
        app.register_blueprint(updates_bp)
        self.client = app.test_client()
        self.settings = {
            "pi_host": "192.0.2.10",
            "pi_user": "pi",
            "auth_method": "key",
            "ssh_key_path": "/fake/key",
            "password": "",
        }

    def _common_patches(self):
        return (
            patch.object(views_updates, "_get_active_ssh_settings", return_value=self.settings),
            patch.object(views_updates, "_is_configured", return_value=True),
            patch.object(views_updates, "ssh_connect", return_value=Mock()),
        )

    def test_reboot_check_can_clear_after_restart(self):
        settings, configured, connect = self._common_patches()
        with settings, configured, connect, patch.object(
            views_updates, "ssh_exec", return_value=(0, "NO_REBOOT\n", "")
        ):
            response = self.client.post(
                "/updates/run", json={"action": "reboot_required"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["stdout"], "NO_REBOOT\n")

    def test_reboot_check_detects_pending_new_kernel(self):
        settings, configured, connect = self._common_patches()
        with settings, configured, connect, patch.object(
            views_updates, "ssh_exec", return_value=(0, "REBOOT_REQUIRED\n", "")
        ):
            response = self.client.post(
                "/updates/run", json={"action": "reboot_required"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("REBOOT_REQUIRED", response.get_json()["stdout"])

    def test_reboot_command_is_dispatched_after_sudo_validation(self):
        fake_ssh = Mock()
        with patch.object(views_updates, "_get_active_ssh_settings", return_value=self.settings), \
             patch.object(views_updates, "_is_configured", return_value=True), \
             patch.object(views_updates, "ssh_connect", return_value=fake_ssh), \
             patch.object(views_updates, "ssh_exec", return_value=(0, "", "")), \
             patch.object(views_updates.time, "sleep"):
            response = self.client.post(
                "/updates/run",
                json={"action": "reboot_now", "sudo_password": "secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["rebooting"])
        fake_ssh.exec_command.assert_called_once_with("sudo -n reboot", timeout=10)

    def test_reboot_is_not_sent_when_sudo_validation_fails(self):
        fake_ssh = Mock()
        with patch.object(views_updates, "_get_active_ssh_settings", return_value=self.settings), \
             patch.object(views_updates, "_is_configured", return_value=True), \
             patch.object(views_updates, "ssh_connect", return_value=fake_ssh), \
             patch.object(views_updates, "ssh_exec", return_value=(1, "", "bad password")):
            response = self.client.post(
                "/updates/run",
                json={"action": "reboot_now", "sudo_password": "wrong"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(fake_ssh.exec_command.called)


if __name__ == "__main__":
    unittest.main()
