import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from routes.settings.views_profiles import profiles_bp
from routes.settings import views_profiles
from routes.settings import profiles_data


class _MemoryFile:
    def __init__(self, content=""):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.content

    def write(self, value):
        self.content += value


class _FakeSftp:
    def __init__(self):
        self.files = {}

    def mkdir(self, _):
        return None

    def chmod(self, *_):
        return None

    def close(self):
        return None

    def file(self, path, mode, _bufsize=-1):
        if mode == "r" and path not in self.files:
            raise IOError("not found")
        if mode == "w":
            self.files[path] = _MemoryFile()
        elif mode == "a" and path not in self.files:
            self.files[path] = _MemoryFile()
        return self.files[path]


class SettingsSshKeyFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        self.app.register_blueprint(profiles_bp)
        self.client = self.app.test_client()
        self.profile = {
            "id": "profile-1",
            "name": "RaspberryPi",
            "pi_host": "192.0.2.10",
            "pi_user": "pi",
            "auth_method": "password",
            "ssh_key_path": "",
            "password": "",
        }

    def test_new_profile_starts_with_password_authentication(self):
        data = {"profiles": [], "active_profile_id": None, "default_profile_id": None}
        with self.app.app_context(), \
             patch.object(profiles_data, "_ensure_store", return_value=data), \
             patch.object(profiles_data, "_write_store"):
            profile = profiles_data.create_new_profile("First Linux")

        self.assertEqual(profile["auth_method"], "password")

    def test_suggestion_reports_an_existing_keypair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = os.path.join(temp_dir, "id_RaspberryPi")
            open(key_path, "w", encoding="utf-8").close()
            with open(key_path + ".pub", "w", encoding="utf-8") as public_key:
                public_key.write("ssh-ed25519 AAAATEST monitor@test\n")
            data = {"profiles": [self.profile]}
            key = Mock()
            key.get_name.return_value = "ssh-ed25519"
            key.get_base64.return_value = "AAAATEST"
            with patch.object(views_profiles.profiles_data, "_ensure_store", return_value=data), \
                 patch.object(views_profiles.profiles_data, "_find", return_value=self.profile), \
                 patch.object(views_profiles.ssh_utils, "get_key_candidates", return_value=[]), \
                 patch.object(views_profiles.ssh_utils, "_load_private_key", return_value=key):
                response = self.client.get(
                    "/profiles/suggest-key-path",
                    query_string={"id": self.profile["id"], "path": key_path},
                )

        status = response.get_json()["key_status"]
        self.assertTrue(status["private_exists"])
        self.assertTrue(status["private_valid"])
        self.assertTrue(status["public_exists"])
        self.assertTrue(status["public_valid"])

    def test_suggestion_marks_a_corrupt_private_key_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = os.path.join(temp_dir, "id_RaspberryPi")
            with open(key_path, "w", encoding="utf-8") as key_file:
                key_file.write("not a key")
            data = {"profiles": [self.profile]}
            with patch.object(views_profiles.profiles_data, "_ensure_store", return_value=data), \
                 patch.object(views_profiles.profiles_data, "_find", return_value=self.profile), \
                 patch.object(views_profiles.ssh_utils, "get_key_candidates", return_value=[]), \
                 patch.object(views_profiles.ssh_utils, "_load_private_key", side_effect=ValueError("bad key")):
                response = self.client.get(
                    "/profiles/suggest-key-path",
                    query_string={"id": self.profile["id"], "path": key_path},
                )

        status = response.get_json()["key_status"]
        self.assertTrue(status["private_exists"])
        self.assertFalse(status["private_valid"])

    def test_generate_returns_conflict_for_existing_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = os.path.join(temp_dir, "id_RaspberryPi")
            open(key_path, "w", encoding="utf-8").close()
            data = {"profiles": [self.profile]}
            generate = Mock()
            with patch.object(views_profiles.profiles_data, "_ensure_store", return_value=data), \
                 patch.object(views_profiles.profiles_data, "_find", return_value=self.profile), \
                 patch.object(views_profiles.ssh_utils, "generate_ssh_keypair", generate):
                response = self.client.post(
                    "/profiles/gen-key",
                    json={"id": self.profile["id"], "key_path": key_path},
                )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(generate.called)

    def test_missing_public_key_can_be_rebuilt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = os.path.join(temp_dir, "id_RaspberryPi")
            open(key_path, "w", encoding="utf-8").close()
            profile = dict(self.profile, ssh_key_path=key_path)
            data = {"profiles": [profile], "active_profile_id": None}
            key = Mock()
            key.get_name.return_value = "ssh-ed25519"
            key.get_base64.return_value = "AAAATEST"
            with patch.object(views_profiles.profiles_data, "_ensure_store", return_value=data), \
                 patch.object(views_profiles.profiles_data, "_find", return_value=profile), \
                 patch.object(views_profiles.profiles_data, "_write_store"), \
                 patch.object(views_profiles.ssh_utils, "_load_private_key", return_value=key):
                response = self.client.post(
                    "/profiles/repair-key",
                    json={"id": profile["id"], "key_path": key_path},
                )
            with open(key_path + ".pub", "r", encoding="utf-8") as public_key:
                rebuilt = public_key.read()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(rebuilt, "ssh-ed25519 AAAATEST\n")

    def test_repair_is_a_noop_for_a_valid_keypair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = os.path.join(temp_dir, "id_RaspberryPi")
            open(key_path, "w", encoding="utf-8").close()
            with open(key_path + ".pub", "w", encoding="utf-8") as public_key:
                public_key.write("ssh-ed25519 AAAATEST monitor@test\n")
            profile = dict(self.profile, ssh_key_path=key_path)
            data = {"profiles": [profile], "active_profile_id": None}
            key = Mock()
            key.get_name.return_value = "ssh-ed25519"
            key.get_base64.return_value = "AAAATEST"
            with patch.object(views_profiles.profiles_data, "_ensure_store", return_value=data), \
                 patch.object(views_profiles.profiles_data, "_find", return_value=profile), \
                 patch.object(views_profiles.ssh_utils, "_load_private_key", return_value=key):
                response = self.client.post(
                    "/profiles/repair-key",
                    json={"id": profile["id"], "key_path": key_path},
                )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["repaired"])

    def test_delete_key_returns_profile_to_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = os.path.join(temp_dir, "id_RaspberryPi")
            open(key_path, "w", encoding="utf-8").close()
            open(key_path + ".pub", "w", encoding="utf-8").close()
            profile = dict(self.profile, auth_method="key", ssh_key_path=key_path)
            data = {"profiles": [profile], "active_profile_id": None}
            with patch.object(views_profiles.profiles_data, "_ensure_store", return_value=data), \
                 patch.object(views_profiles.profiles_data, "_find", return_value=profile), \
                 patch.object(views_profiles.profiles_data, "_write_store"):
                response = self.client.post(
                    "/profiles/delete-key",
                    json={"id": profile["id"], "key_path": key_path},
                )

            self.assertFalse(os.path.exists(key_path))
            self.assertFalse(os.path.exists(key_path + ".pub"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(profile["auth_method"], "password")
        self.assertEqual(profile["ssh_key_path"], "")

    def test_strict_key_test_disables_password_fallback(self):
        connect = Mock(return_value=Mock())
        with patch.object(views_profiles.ssh_utils, "ssh_connect", connect):
            response = self.client.post("/profiles/test", json={
                "pi_host": "192.0.2.10",
                "pi_user": "pi",
                "auth_method": "key",
                "ssh_key_path": "C:/fake/key",
                "strict_auth": True,
            })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertFalse(connect.call_args.kwargs["allow_fallback"])

    def test_install_accepts_text_home_output_and_writes_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = os.path.join(temp_dir, "id_RaspberryPi")
            open(key_path, "w", encoding="utf-8").close()
            with open(key_path + ".pub", "w", encoding="utf-8") as public_key:
                public_key.write("ssh-ed25519 AAAATEST monitor@test\n")
            profile = dict(self.profile)
            data = {"profiles": [profile]}
            sftp = _FakeSftp()
            ssh = Mock()
            ssh.open_sftp.return_value = sftp
            with patch.object(views_profiles.profiles_data, "_ensure_store", return_value=data), \
                 patch.object(views_profiles.profiles_data, "_find", return_value=profile), \
                 patch.object(views_profiles.ssh_utils, "ssh_connect", return_value=ssh), \
                 patch.object(views_profiles.ssh_utils, "ssh_exec", return_value=(0, "/home/pi\n", "")):
                response = self.client.post(
                    "/profiles/install-key",
                    json={"id": profile["id"], "password": "secret", "key_path": key_path},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["installed_to"], "/home/pi/.ssh/authorized_keys")
        self.assertIn("AAAATEST", sftp.files["/home/pi/.ssh/authorized_keys"].content)


if __name__ == "__main__":
    unittest.main()
