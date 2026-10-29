"""Loop-guard state: tool-name canonicalisation across hosts."""
import pytest

from tokeneconomizer.loopguard import SpiralState, canon_tool


@pytest.mark.xfail(strict=True, reason="red test R10: the Cowork green build maps the device shell")
def test_cowork_device_shell_is_bash():
    """Claude Cowork's shell on the person's computer arrives through the remote-devices bridge.
    Unmapped, the loop guard never reads its command text."""
    assert canon_tool("mcp__remote-devices__device_bash") == "bash"
    s = SpiralState()
    s.update("mcp__remote-devices__device_bash", {"command": "python -m pytest tests"}, "1 failed")
    assert s.test_runs == 1
