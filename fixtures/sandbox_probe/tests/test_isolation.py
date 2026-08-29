import socket
from pathlib import Path

import pytest


def test_network_is_disabled() -> None:
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 53), timeout=0.5)


def test_root_filesystem_is_read_only_but_workspace_is_writable() -> None:
    with pytest.raises(OSError):
        Path("/evodev-rootfs-probe").write_text("blocked", encoding="utf-8")

    probe = Path("workspace-write-probe.txt")
    probe.write_text("allowed", encoding="utf-8")
    probe.unlink()


def test_capabilities_privilege_escalation_and_docker_socket_are_blocked() -> None:
    status = Path("/proc/self/status").read_text(encoding="utf-8")

    assert "CapEff:\t0000000000000000" in status
    assert "NoNewPrivs:\t1" in status
    assert not Path("/var/run/docker.sock").exists()


def test_cgroup_limits_are_applied_when_v2_files_are_available() -> None:
    memory = Path("/sys/fs/cgroup/memory.max")
    pids = Path("/sys/fs/cgroup/pids.max")
    cpu = Path("/sys/fs/cgroup/cpu.max")
    if not all(path.exists() for path in (memory, pids, cpu)):
        pytest.skip("cgroup v2 files are unavailable")

    assert int(memory.read_text(encoding="utf-8")) <= 1024**3
    assert int(pids.read_text(encoding="utf-8")) <= 128
    quota, period = cpu.read_text(encoding="utf-8").split()
    assert quota != "max"
    assert int(quota) / int(period) <= 1.0
