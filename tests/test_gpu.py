import subprocess
import unittest
from unittest.mock import Mock, patch

from scan2read.ocr.gpu import (detect_nvidia_gpu, gpu_paddle_installed, gpu_utilization,
                               install_gpu_support, paddle_version)


class DetectNvidiaGpuTests(unittest.TestCase):
    def test_returns_name_when_present(self):
        completed = Mock(returncode=0, stdout="NVIDIA GeForce RTX 3070\n")
        with patch("scan2read.ocr.gpu.subprocess.run", return_value=completed):
            self.assertEqual(detect_nvidia_gpu(), "NVIDIA GeForce RTX 3070")

    def test_returns_none_when_nvidia_smi_missing(self):
        with patch("scan2read.ocr.gpu.subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(detect_nvidia_gpu())

    def test_returns_none_on_timeout(self):
        with patch("scan2read.ocr.gpu.subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 10)):
            self.assertIsNone(detect_nvidia_gpu())

    def test_returns_none_on_nonzero_exit(self):
        completed = Mock(returncode=1, stdout="")
        with patch("scan2read.ocr.gpu.subprocess.run", return_value=completed):
            self.assertIsNone(detect_nvidia_gpu())

    def test_returns_none_on_blank_output(self):
        completed = Mock(returncode=0, stdout="\n")
        with patch("scan2read.ocr.gpu.subprocess.run", return_value=completed):
            self.assertIsNone(detect_nvidia_gpu())


class GpuUtilizationTests(unittest.TestCase):
    def test_parses_utilization_and_memory(self):
        completed = Mock(returncode=0, stdout="63, 4200, 8192\n")
        with patch("scan2read.ocr.gpu.subprocess.run", return_value=completed):
            self.assertEqual(gpu_utilization(),
                             {"utilization_percent": 63, "memory_used_mb": 4200, "memory_total_mb": 8192})

    def test_returns_none_when_nvidia_smi_missing(self):
        with patch("scan2read.ocr.gpu.subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(gpu_utilization())

    def test_returns_none_on_timeout(self):
        with patch("scan2read.ocr.gpu.subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 5)):
            self.assertIsNone(gpu_utilization())

    def test_returns_none_on_nonzero_exit(self):
        completed = Mock(returncode=1, stdout="")
        with patch("scan2read.ocr.gpu.subprocess.run", return_value=completed):
            self.assertIsNone(gpu_utilization())

    def test_returns_none_on_unparseable_output(self):
        completed = Mock(returncode=0, stdout="not, a, number\n")
        with patch("scan2read.ocr.gpu.subprocess.run", return_value=completed):
            self.assertIsNone(gpu_utilization())

    def test_returns_none_on_blank_output(self):
        completed = Mock(returncode=0, stdout="\n")
        with patch("scan2read.ocr.gpu.subprocess.run", return_value=completed):
            self.assertIsNone(gpu_utilization())


class PackageStateTests(unittest.TestCase):
    def test_gpu_paddle_installed_reflects_distribution_presence(self):
        with patch("scan2read.ocr.gpu.version", return_value="3.3.1"):
            self.assertTrue(gpu_paddle_installed())
        from importlib.metadata import PackageNotFoundError
        with patch("scan2read.ocr.gpu.version", side_effect=PackageNotFoundError):
            self.assertFalse(gpu_paddle_installed())

    def test_paddle_version_falls_back_to_gpu_distribution(self):
        from importlib.metadata import PackageNotFoundError
        def fake_version(name):
            if name == "paddlepaddle":
                raise PackageNotFoundError
            return "3.3.1"
        with patch("scan2read.ocr.gpu.version", side_effect=fake_version):
            self.assertEqual(paddle_version(), "3.3.1")


class InstallGpuSupportTests(unittest.TestCase):
    def test_uninstalls_cpu_build_before_installing_gpu_build(self):
        process = Mock(stdout=iter(["ok\n"]))
        process.wait.return_value = 0
        with patch("scan2read.ocr.gpu.subprocess.Popen", return_value=process) as popen:
            list(install_gpu_support(version_pin="3.3.1", index_url="https://example.invalid/"))
        commands = [call.args[0] for call in popen.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertIn("uninstall", commands[0])
        self.assertIn("paddlepaddle", commands[0])
        self.assertNotIn("paddlepaddle-gpu", commands[0])
        self.assertIn("paddlepaddle-gpu==3.3.1", commands[1])
        self.assertIn("https://example.invalid/", commands[1])

    def test_stops_and_raises_if_a_step_fails(self):
        process = Mock(stdout=iter(["failure\n"]))
        process.wait.return_value = 1
        with patch("scan2read.ocr.gpu.subprocess.Popen", return_value=process):
            with self.assertRaises(RuntimeError):
                list(install_gpu_support())

    def test_yields_output_lines_from_both_steps(self):
        first = Mock(stdout=iter(["uninstalling\n"]))
        first.wait.return_value = 0
        second = Mock(stdout=iter(["installing\n"]))
        second.wait.return_value = 0
        with patch("scan2read.ocr.gpu.subprocess.Popen", side_effect=[first, second]):
            lines = list(install_gpu_support())
        self.assertEqual(lines, ["uninstalling\n", "installing\n"])
