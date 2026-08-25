"""
Test suite for aws-ssm-connect CLI.

Spec requirements covered:
  R1  Lazy loading (no import-time read)
  R2  --help exits 0 with/without config
  R3  Completion exits 0, no traceback when config absent
  R4  --env completion: absent → [], present → suggests section keys
  R5  Missing config: friendly English stderr, exit≠0, no traceback, no import-time sys.exit
  R6  Malformed YAML: friendly error, exit≠0, no traceback; completion → []
  R7  Behavior preservation with valid config
  R8  pytest + CliRunner suite runnable via `pytest`
  R9  Config discovery 4-tier precedence
"""

import os
import textwrap
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(aws_connect):
    """Return a bare Click context for the cli group (used in completion tests)."""
    import click
    return click.Context(aws_connect.cli)


def _invoke_complete(aws_connect, service, incomplete=""):
    """Directly invoke the _complete_env callback for a service."""
    cb = aws_connect._complete_env(service)
    ctx = _make_ctx(aws_connect)
    # Obtain any param (the callback signature is (ctx, param, incomplete))
    param = None
    return cb(ctx, param, incomplete)


# ---------------------------------------------------------------------------
# Phase 4.1 — help root no config: exit 0, no Traceback (R2)
# ---------------------------------------------------------------------------


def test_help_root_no_config(runner, aws_connect, cwd_no_config):
    result = runner.invoke(aws_connect.cli, ["--help"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in (result.output or "")


# ---------------------------------------------------------------------------
# Phase 4.2 — help each subcommand no config: exit 0, no traceback (R2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subcommand",
    ["list", "list-instances", "jumphost", "rds", "redis", "opensearch", "eks", "docdb"],
)
def test_help_subcommands_no_config(runner, aws_connect, cwd_no_config, subcommand):
    result = runner.invoke(aws_connect.cli, [subcommand, "--help"])
    assert result.exit_code == 0, f"{subcommand}: {result.output}"
    assert "Traceback" not in (result.output or "")


# ---------------------------------------------------------------------------
# Phase 4.3 — completion no config: exit 0, no traceback/error (R3)
# ---------------------------------------------------------------------------


def test_completion_no_config(runner, aws_connect, cwd_no_config):
    """
    Shell completion must not raise or print an error when config is absent.
    We call _complete_env for each service and assert it returns an empty list.
    """
    for service in ("rds", "redis", "eks", "opensearch", "ec2"):
        completions = _invoke_complete(aws_connect, service)
        assert completions == [], f"Expected [] for {service} when no config, got {completions}"


# ---------------------------------------------------------------------------
# Phase 4.4 — _complete_env absent → [] (R4)
# ---------------------------------------------------------------------------


def test_env_completion_absent_config(aws_connect, cwd_no_config):
    completions = _invoke_complete(aws_connect, "rds")
    assert completions == []


# ---------------------------------------------------------------------------
# Phase 4.5 — _complete_env present → contains key (R4)
# ---------------------------------------------------------------------------


def test_env_completion_present_config(aws_connect, cwd_with_config):
    completions = _invoke_complete(aws_connect, "rds", incomplete="")
    keys = [c if isinstance(c, str) else c.value for c in completions]
    assert "staging" in keys, f"Expected 'staging' in completions, got {keys}"


# ---------------------------------------------------------------------------
# Phase 4.6 — real command missing config: exit≠0, friendly message, no Traceback (R5)
# ---------------------------------------------------------------------------


def test_real_command_missing_config(runner, aws_connect, cwd_no_config):
    result = runner.invoke(aws_connect.cli, ["rds", "--env", "staging"])
    assert result.exit_code != 0, "Expected non-zero exit when config is missing"
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "environments.yaml" in output, f"Expected 'environments.yaml' in output: {output!r}"
    assert "cp environments.yaml.example environments.yaml" in output, (
        f"Expected copy hint in output: {output!r}"
    )
    assert "Traceback" not in output, f"Traceback found in output: {output!r}"


# ---------------------------------------------------------------------------
# Phase 4.7 — real command malformed config: exit≠0, friendly message, no Traceback (R6)
# ---------------------------------------------------------------------------


def test_real_command_malformed_config(runner, aws_connect, cwd_malformed_config):
    result = runner.invoke(aws_connect.cli, ["rds", "--env", "staging"])
    assert result.exit_code != 0, "Expected non-zero exit when config is malformed"
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "environments.yaml" in output, f"Expected 'environments.yaml' in output: {output!r}"
    assert "Traceback" not in output, f"Traceback found in output: {output!r}"


# ---------------------------------------------------------------------------
# Phase 4.8 — completion malformed → [] (R6)
# ---------------------------------------------------------------------------


def test_completion_malformed_config(aws_connect, cwd_malformed_config):
    completions = _invoke_complete(aws_connect, "rds")
    assert completions == [], f"Expected [] for malformed config, got {completions}"


# ---------------------------------------------------------------------------
# Phase 4.9 — behavior preservation rds: mock_subprocess, ssm start-session, exit 0 (R7)
# ---------------------------------------------------------------------------


def test_behavior_preservation_rds(runner, aws_connect, cwd_with_config, mock_subprocess):
    result = runner.invoke(aws_connect.cli, ["rds", "--env", "staging"])
    # os.system should have been called
    assert mock_subprocess.called, "Expected os.system to be called"
    # The command passed to os.system should reference ssm start-session
    call_args = mock_subprocess.call_args[0][0]
    assert "ssm start-session" in call_args, (
        f"Expected 'ssm start-session' in os.system call: {call_args!r}"
    )
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {result.output}"


# ---------------------------------------------------------------------------
# Phase 4.10 — list no config: exit≠0, "environments.yaml" in output (R5)
# ---------------------------------------------------------------------------


def test_list_no_config(runner, aws_connect, cwd_no_config):
    result = runner.invoke(aws_connect.cli, ["list"])
    assert result.exit_code != 0, "Expected non-zero exit for list when config is missing"
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "environments.yaml" in output, f"Expected 'environments.yaml' in output: {output!r}"


# ---------------------------------------------------------------------------
# REL-006 — negative validation paths for jumphost / list-instances
# ---------------------------------------------------------------------------


def _combined_output(result):
    return (result.output or "") + (
        result.stderr if hasattr(result, "stderr") and result.stderr else ""
    )


@pytest.mark.parametrize("command", ["jumphost", "list-instances"])
def test_invalid_env_valid_config(runner, aws_connect, cwd_with_config, command):
    """Wrong --env against valid config: exit≠0, 'not found', available list, no Traceback."""
    result = runner.invoke(aws_connect.cli, [command, "--env", "does-not-exist"])
    assert result.exit_code != 0, f"{command}: expected non-zero exit for unknown env"
    output = _combined_output(result)
    assert "not found" in output, f"{command}: expected 'not found' message: {output!r}"
    assert "staging" in output, f"{command}: expected available env 'staging' listed: {output!r}"
    assert "Traceback" not in output, f"{command}: Traceback found: {output!r}"


def test_interactive_prompt_lists_envs(runner, aws_connect, cwd_with_config, mock_subprocess):
    """
    Running a service command with no --env prompts interactively AND lists the
    available environments in the prompt (regression: dropping click.Choice must
    not turn the prompt into a bare 'Environment:').
    """
    result = runner.invoke(aws_connect.cli, ["rds"], input="staging\n")
    assert result.exit_code == 0, result.output
    # Click renders a Choice prompt as "Environment (prod, staging): "
    assert "Environment (" in result.output, f"Prompt did not list choices: {result.output!r}"
    assert "staging" in result.output and "prod" in result.output, (
        f"Available envs not shown in prompt: {result.output!r}"
    )


def test_interactive_prompt_no_config_section(runner, aws_connect, cwd_config_no_ec2, mock_subprocess):
    """No envs for the service → interactive prompt errors cleanly, no Traceback."""
    result = runner.invoke(aws_connect.cli, ["redis"], input="\n")
    assert result.exit_code != 0
    output = _combined_output(result)
    assert "redis" in output, f"Expected 'redis' referenced: {output!r}"
    assert "Traceback" not in output, f"Traceback found: {output!r}"


@pytest.mark.parametrize("command", ["jumphost", "list-instances"])
def test_missing_ec2_section(runner, aws_connect, cwd_config_no_ec2, command):
    """Config without an 'ec2' section: exit≠0, friendly message, no Traceback."""
    result = runner.invoke(aws_connect.cli, [command, "--env", "staging"])
    assert result.exit_code != 0, f"{command}: expected non-zero exit when 'ec2' section missing"
    output = _combined_output(result)
    assert "ec2" in output, f"{command}: expected 'ec2' referenced in message: {output!r}"
    assert "Traceback" not in output, f"{command}: Traceback found: {output!r}"


# ---------------------------------------------------------------------------
# Redis endpoint resolution (redis-endpoint-resolution change)
# ---------------------------------------------------------------------------


def test_redis_cluster_primary_endpoint(
    runner, aws_connect, cwd_with_redis_cluster_config, mock_subprocess_elasticache_primary
):
    """cluster env + PrimaryEndpoint: SSM command uses primary address; exit 0."""
    mock_os_system, _ = mock_subprocess_elasticache_primary
    result = runner.invoke(aws_connect.cli, ["redis", "--env", "cluster-env"])
    assert result.exit_code == 0, f"Expected exit 0: {result.output}"
    assert mock_os_system.called, "Expected os.system to be called"
    call_arg = mock_os_system.call_args[0][0]
    assert 'host="primary.cache.example.com"' in call_arg, (
        f"Expected primary address in SSM host= parameter: {call_arg!r}"
    )
    assert "Traceback" not in result.output, f"Traceback found: {result.output!r}"


def test_redis_cluster_config_endpoint_fallback(
    runner, aws_connect, cwd_with_redis_cluster_config, mock_subprocess_elasticache_config_ep
):
    """cluster env + ConfigurationEndpoint (PrimaryEndpoint null): SSM command uses config address; exit 0."""
    mock_os_system, _ = mock_subprocess_elasticache_config_ep
    result = runner.invoke(aws_connect.cli, ["redis", "--env", "cluster-env"])
    assert result.exit_code == 0, f"Expected exit 0: {result.output}"
    assert mock_os_system.called, "Expected os.system to be called"
    call_arg = mock_os_system.call_args[0][0]
    assert 'host="config.cache.example.com"' in call_arg, (
        f"Expected configuration endpoint in SSM host= parameter: {call_arg!r}"
    )
    assert "Traceback" not in result.output, f"Traceback found: {result.output!r}"


def test_redis_cluster_aws_failure(
    runner, aws_connect, cwd_with_redis_cluster_config, mock_subprocess_elasticache_failure
):
    """cluster env + AWS lookup failure: exit≠0, friendly error, no Traceback, os.system not called with ssm."""
    mock_os_system, mock_run = mock_subprocess_elasticache_failure
    result = runner.invoke(aws_connect.cli, ["redis", "--env", "cluster-env"])
    assert result.exit_code != 0, f"Expected non-zero exit on AWS failure, got {result.exit_code}"
    output = _combined_output(result)
    assert "Traceback" not in output, f"Traceback found: {output!r}"
    assert "Redis endpoint" in output or "Error" in output, (
        f"Expected friendly error message: {output!r}"
    )
    # the elasticache lookup must actually have been attempted (guards against
    # side_effect desync feeding the wrong mock return to the wrong call)
    assert any(
        "describe-replication-groups" in (c[0][0] if c[0] else "")
        for c in mock_run.call_args_list
    ), "Expected describe-replication-groups to be attempted"
    # os.system must NOT be reached at all — failure exits before port-forward
    assert not mock_os_system.called, "os.system must not run when endpoint resolution fails"


def test_redis_cluster_group_not_found_null(
    runner, aws_connect, cwd_with_redis_cluster_config, mock_subprocess_elasticache_null
):
    """cluster env where the AWS query returns the JSON literal `null` (group not
    found): friendly error, exit≠0, NO uncaught AttributeError, os.system not reached."""
    mock_os_system, mock_run = mock_subprocess_elasticache_null
    result = runner.invoke(aws_connect.cli, ["redis", "--env", "cluster-env"])
    # The bug this guards against: json.loads("null") -> None, then rg.get(...)
    # would raise AttributeError. CliRunner swallows it into result.exception,
    # so assert on the exception type, not just output text.
    assert not isinstance(result.exception, AttributeError), (
        f"Uncaught AttributeError from null AWS response: {result.exception!r}"
    )
    assert result.exit_code != 0, f"Expected non-zero exit, got {result.exit_code}"
    output = _combined_output(result)
    assert "Traceback" not in output, f"Traceback found: {output!r}"
    assert "Redis endpoint" in output or "Error" in output, (
        f"Expected friendly error message: {output!r}"
    )
    assert not mock_os_system.called, "os.system must not run when the group is not found"


def test_redis_endpoint_literal_no_aws_call(
    runner, aws_connect, cwd_with_config, mock_subprocess
):
    """endpoint-only env: SSM uses literal endpoint; no describe-replication-groups call made."""
    result = runner.invoke(aws_connect.cli, ["redis", "--env", "staging"])
    assert result.exit_code == 0, f"Expected exit 0: {result.output}"
    # os.system must have been called with the literal endpoint
    call_arg = mock_subprocess.call_args[0][0]
    assert "my-endpoint.cache.amazonaws.com" in call_arg, (
        f"Expected literal endpoint in SSM command: {call_arg!r}"
    )
    # run_command must NOT have been called for describe-replication-groups
    run_command_mock = aws_connect.run_command
    elasticache_calls = [
        c for c in run_command_mock.call_args_list
        if "describe-replication-groups" in (c[0][0] if c[0] else "")
    ]
    assert not elasticache_calls, (
        f"run_command was called with describe-replication-groups unexpectedly: {elasticache_calls}"
    )
    assert "Traceback" not in result.output, f"Traceback found: {result.output!r}"


def test_redis_neither_cluster_nor_endpoint(
    runner, aws_connect, cwd_with_redis_bare_config, mock_subprocess
):
    """env with neither cluster nor endpoint: exit≠0, friendly error, no Traceback."""
    result = runner.invoke(aws_connect.cli, ["redis", "--env", "bare-env"])
    assert result.exit_code != 0, f"Expected non-zero exit, got {result.exit_code}"
    output = _combined_output(result)
    assert "Traceback" not in output, f"Traceback found: {output!r}"
    assert "cluster" in output or "endpoint" in output, (
        f"Expected friendly error mentioning missing keys: {output!r}"
    )


# ---------------------------------------------------------------------------
# Region configuration (docdb-port-forwarding change)
# ---------------------------------------------------------------------------


def _ssm_call_arg(mock_os_system):
    return mock_os_system.call_args[0][0]


@pytest.mark.parametrize("command,env", [("rds", "staging"), ("redis", "staging"),
                                          ("opensearch", "staging")])
def test_region_default_when_absent(runner, aws_connect, cwd_with_config, mock_subprocess, command, env):
    """No 'region' key configured: existing commands keep using DEFAULT_REGION
    (us-east-1) in the SSM command — behavior preservation for the refactor."""
    result = runner.invoke(aws_connect.cli, [command, "--env", env])
    assert result.exit_code == 0, result.output
    call_arg = _ssm_call_arg(mock_subprocess)
    assert "--region us-east-1" in call_arg, (
        f"Expected default region in SSM command: {call_arg!r}"
    )


def test_region_override_redis(runner, aws_connect, cwd_with_region_config, mock_subprocess):
    """redis env with 'region: us-west-2' propagates into the SSM command."""
    result = runner.invoke(aws_connect.cli, ["redis", "--env", "region-env"])
    assert result.exit_code == 0, result.output
    call_arg = _ssm_call_arg(mock_subprocess)
    assert "--region us-west-2" in call_arg, (
        f"Expected overridden region in SSM command: {call_arg!r}"
    )
    assert "--region us-east-1" not in call_arg, (
        f"Default region must not leak when override is set: {call_arg!r}"
    )


def test_region_override_reaches_instance_lookup(runner, aws_connect, cwd_with_region_config, monkeypatch):
    """The instance-id lookup (run_command) must also receive the overridden region,
    not just the final SSM command."""
    mock_run = MagicMock(return_value=("fake-id", 0))
    monkeypatch.setattr(aws_connect, "run_command", mock_run)
    monkeypatch.setattr("os.system", MagicMock(return_value=0))
    result = runner.invoke(aws_connect.cli, ["redis", "--env", "region-env"])
    assert result.exit_code == 0, result.output
    lookup_cmd = mock_run.call_args_list[0][0][0]
    assert "--region us-west-2" in lookup_cmd, (
        f"Expected instance lookup to use overridden region: {lookup_cmd!r}"
    )


def test_region_absent_never_produces_none_token(runner, aws_connect, cwd_with_config, mock_subprocess):
    """Absent region must resolve to the default, never leak a literal 'None'."""
    result = runner.invoke(aws_connect.cli, ["redis", "--env", "staging"])
    assert result.exit_code == 0, result.output
    call_arg = _ssm_call_arg(mock_subprocess)
    assert "--region None" not in call_arg, f"Leaked '--region None': {call_arg!r}"


def test_region_helper_resolves_from_config():
    """Unit test for `_region(config)`: config value wins; absent/None/empty fall
    back to DEFAULT_REGION."""
    import aws_connect as ac
    assert ac._region({"region": "eu-west-1"}) == "eu-west-1"
    assert ac._region({}) == ac.DEFAULT_REGION
    assert ac._region({"region": None}) == ac.DEFAULT_REGION
    assert ac._region({"region": ""}) == ac.DEFAULT_REGION


def test_region_eks_kubeconfig_arn_and_flag(runner, aws_connect, monkeypatch, tmp_path, mock_subprocess):
    """EKS: region threaded into the kubeconfig cluster ARN and
    `update-kubeconfig --region`."""
    config = textwrap.dedent("""\
        eks:
          region-env:
            profile: my-profile
            jumphost: my-jumphost
            cluster: my-eks-cluster
            port: '8443'
            region: eu-west-1
            account_id: '123456789012'
    """)
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(config)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    aws_connect._ENVIRONMENTS_CACHE = None

    calls = []
    monkeypatch.setattr("os.system", lambda cmd: calls.append(cmd) or 0)

    result = runner.invoke(
        aws_connect.cli, ["eks", "--env", "region-env", "--configure-kubeconfig"]
    )
    assert result.exit_code == 0, result.output
    joined = "\n".join(calls)
    assert "arn:aws:eks:eu-west-1:123456789012:cluster/my-eks-cluster" in joined, (
        f"Expected region-aware kubeconfig ARN: {joined!r}"
    )
    assert "update-kubeconfig" in joined and "--region eu-west-1" in joined, (
        f"Expected update-kubeconfig --region eu-west-1: {joined!r}"
    )


# ---------------------------------------------------------------------------
# docdb command (docdb-port-forwarding change)
# ---------------------------------------------------------------------------


def test_docdb_valid_env_opens_tunnel(runner, aws_connect, cwd_with_docdb_config, mock_subprocess):
    """Valid docdb env: resolves jumphost, starts SSM port-forwarding session to
    the literal endpoint:port, prints warning, exit 0."""
    result = runner.invoke(aws_connect.cli, ["docdb", "--env", "production"])
    assert result.exit_code == 0, result.output
    assert mock_subprocess.called, "Expected os.system to be called"
    call_arg = _ssm_call_arg(mock_subprocess)
    assert "AWS-StartPortForwardingSessionToRemoteHost" in call_arg
    assert 'host="my-docdb-cluster.cluster-xxxx.us-west-2.docdb.amazonaws.com"' in call_arg
    assert 'portNumber="27017"' in call_arg
    assert "--region us-west-2" in call_arg
    assert "Connecting to production DocumentDB" in result.output


def test_docdb_local_port_override(runner, aws_connect, cwd_with_docdb_config, mock_subprocess):
    """--local-port overrides localPortNumber while remote portNumber stays from config."""
    result = runner.invoke(
        aws_connect.cli, ["docdb", "--env", "production", "--local-port", "28000"]
    )
    assert result.exit_code == 0, result.output
    call_arg = _ssm_call_arg(mock_subprocess)
    assert 'localPortNumber="28000"' in call_arg
    assert 'portNumber="27017"' in call_arg


def test_docdb_missing_section(runner, aws_connect, cwd_with_config, mock_subprocess):
    """No top-level 'docdb' key in environments.yaml: exit != 0, error names 'docdb'."""
    result = runner.invoke(aws_connect.cli, ["docdb", "--env", "production"])
    assert result.exit_code != 0
    assert "docdb" in result.output
    assert not mock_subprocess.called, "os.system must not run when docdb section is missing"


def test_docdb_missing_endpoint(runner, aws_connect, cwd_with_docdb_bare_config, mock_subprocess):
    """docdb env missing 'endpoint' key: exit != 0, error names 'endpoint'."""
    result = runner.invoke(aws_connect.cli, ["docdb", "--env", "bare-env"])
    assert result.exit_code != 0
    assert "endpoint" in result.output
    assert not mock_subprocess.called, "os.system must not run when endpoint is missing"


def test_docdb_no_warning_when_unconfigured(runner, aws_connect, cwd_with_config, monkeypatch, tmp_path, mock_subprocess):
    """docdb env with no 'warning' key: no warning text printed, still opens tunnel."""
    config = textwrap.dedent("""\
        docdb:
          plain:
            profile: my-profile
            jumphost: my-jumphost
            endpoint: my-docdb.cluster-xxxx.us-east-1.docdb.amazonaws.com
            port: '27017'
    """)
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(config)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    aws_connect._ENVIRONMENTS_CACHE = None

    result = runner.invoke(aws_connect.cli, ["docdb", "--env", "plain"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("\n🎯 Connecting to DocumentDB")
    call_arg = _ssm_call_arg(mock_subprocess)
    assert "my-docdb.cluster-xxxx.us-east-1.docdb.amazonaws.com" in call_arg


def test_docdb_in_command_discovery(runner, aws_connect, cwd_no_config):
    """docdb appears in --help output and shell completion is wired via _complete_env."""
    result = runner.invoke(aws_connect.cli, ["--help"])
    assert result.exit_code == 0, result.output
    assert "docdb" in result.output

    completions = _invoke_complete(aws_connect, "docdb")
    assert completions == [], f"Expected [] with no config, got {completions}"


def test_docdb_completion_offers_configured_envs(aws_connect, cwd_with_docdb_config):
    completions = _invoke_complete(aws_connect, "docdb", incomplete="")
    keys = [c if isinstance(c, str) else c.value for c in completions]
    assert "production" in keys, f"Expected 'production' in completions, got {keys}"


# ---------------------------------------------------------------------------
# Phase 6 — Config discovery 4-tier precedence (R9)
# ---------------------------------------------------------------------------


def test_config_env_var_chosen(aws_connect, monkeypatch, tmp_path):
    """Tier-1 wins: AWS_CONNECT_CONFIG is set and exists; cwd and XDG also have files."""
    # Plant a config file for the env var tier
    env_config = tmp_path / "env_config.yaml"
    env_config.write_text("rds:\n  env-env:\n    profile: env-profile\n    jumphost: h\n    cluster: c\n    port: '5432'\n")

    # Also plant a cwd file (tier-2) and XDG file (tier-3) — they must NOT win
    cwd_config = tmp_path / "environments.yaml"
    cwd_config.write_text("rds:\n  cwd-env:\n    profile: cwd-profile\n    jumphost: h\n    cluster: c\n    port: '5432'\n")

    xdg_dir = tmp_path / "xdg_home" / "aws-ssm-connect"
    xdg_dir.mkdir(parents=True)
    xdg_config = xdg_dir / "environments.yaml"
    xdg_config.write_text("rds:\n  xdg-env:\n    profile: xdg-profile\n    jumphost: h\n    cluster: c\n    port: '5432'\n")

    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(env_config))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_home"))
    aws_connect._ENVIRONMENTS_CACHE = None

    envs = aws_connect.get_environments()
    assert "env-env" in envs.get("rds", {}), (
        f"Expected env-var config to be loaded (env-env key), got: {envs!r}"
    )


def test_config_cwd_chosen(aws_connect, monkeypatch, tmp_path):
    """Tier-2 wins: no env var, ./environments.yaml exists in cwd."""
    cwd_config = tmp_path / "environments.yaml"
    cwd_config.write_text("rds:\n  cwd-env:\n    profile: cwd-profile\n    jumphost: h\n    cluster: c\n    port: '5432'\n")

    # Remove env var (tier-1 absent) and point XDG to empty dir (tier-3 absent)
    monkeypatch.delenv("AWS_CONNECT_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    xdg_empty = tmp_path / "xdg_empty"
    xdg_empty.mkdir(exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_empty))
    # Tier-4 already neutralized by isolate_config
    aws_connect._ENVIRONMENTS_CACHE = None

    envs = aws_connect.get_environments()
    assert "cwd-env" in envs.get("rds", {}), (
        f"Expected cwd config to be loaded (cwd-env key), got: {envs!r}"
    )


def test_config_xdg_chosen(aws_connect, monkeypatch, tmp_path):
    """Tier-3 wins: no env var, no cwd file, XDG config exists."""
    xdg_dir = tmp_path / "xdg_home" / "aws-ssm-connect"
    xdg_dir.mkdir(parents=True)
    xdg_config = xdg_dir / "environments.yaml"
    xdg_config.write_text("rds:\n  xdg-env:\n    profile: xdg-profile\n    jumphost: h\n    cluster: c\n    port: '5432'\n")

    # Tier-1 absent, tier-2 absent (chdir into empty dir), tier-4 neutralized by isolate_config
    monkeypatch.delenv("AWS_CONNECT_CONFIG", raising=False)
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_home"))
    aws_connect._ENVIRONMENTS_CACHE = None

    envs = aws_connect.get_environments()
    assert "xdg-env" in envs.get("rds", {}), (
        f"Expected XDG config to be loaded (xdg-env key), got: {envs!r}"
    )


def test_config_module_fallback_chosen(aws_connect, monkeypatch, tmp_path):
    """Tier-4 wins: no env var, no cwd file, no XDG file; module-relative file exists."""
    module_config = tmp_path / "module_dir" / "environments.yaml"
    module_config.parent.mkdir(parents=True)
    module_config.write_text("rds:\n  module-env:\n    profile: module-profile\n    jumphost: h\n    cluster: c\n    port: '5432'\n")

    # Patch the seam to point at our controlled tmp file
    monkeypatch.setattr(aws_connect, "_module_config_path", lambda: str(module_config))

    # Ensure tiers 1-3 are absent
    monkeypatch.delenv("AWS_CONNECT_CONFIG", raising=False)
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir(exist_ok=True)
    monkeypatch.chdir(empty_cwd)
    xdg_empty = tmp_path / "xdg_empty"
    xdg_empty.mkdir(exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_empty))
    aws_connect._ENVIRONMENTS_CACHE = None

    envs = aws_connect.get_environments()
    assert "module-env" in envs.get("rds", {}), (
        f"Expected module-relative config to be loaded (module-env key), got: {envs!r}"
    )


def test_config_none_raises_ConfigMissingError(runner, aws_connect, monkeypatch, tmp_path):
    """All four tiers absent: ConfigMissingError raised; message lists searched locations."""
    # All tiers already neutralized by isolate_config autouse fixture.
    # Just reset cache and invoke a real command.
    aws_connect._ENVIRONMENTS_CACHE = None

    result = runner.invoke(aws_connect.cli, ["rds", "--env", "staging"])
    assert result.exit_code != 0, "Expected non-zero exit when all config tiers absent"
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "environments.yaml" in output, f"Expected 'environments.yaml' in error output: {output!r}"
    # Message must enumerate ALL searched tiers (it is the sole user guidance)
    assert "Searched locations" in output, f"Expected 'Searched locations' header: {output!r}"
    assert "AWS_CONNECT_CONFIG" in output, f"Expected tier-1 (env var) listed: {output!r}"
    assert "./environments.yaml" in output, f"Expected tier-2 (cwd) listed: {output!r}"
    assert "aws-ssm-connect" in output, f"Expected tier-3 (XDG) path listed: {output!r}"
    assert "Traceback" not in output, f"Traceback found in output: {output!r}"


# ---------------------------------------------------------------------------
# Phase 3 — config link / unlink commands (config-link change)
# ---------------------------------------------------------------------------


def test_config_link_help_no_config(runner, aws_connect):
    """config link --help exits 0 and no Traceback — even when environments.yaml absent."""
    result = runner.invoke(aws_connect.cli, ["config", "link", "--help"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in (result.output or "")


def test_config_unlink_help_no_config(runner, aws_connect):
    """config unlink --help exits 0 and no Traceback."""
    result = runner.invoke(aws_connect.cli, ["config", "unlink", "--help"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in (result.output or "")


def test_config_link_creates_symlink(runner, aws_connect, linkable_source, monkeypatch, tmp_path):
    """config link <source> creates a symlink at the XDG target; exit 0."""
    # Run link with an explicit source path
    result = runner.invoke(aws_connect.cli, ["config", "link", str(linkable_source)])
    assert result.exit_code == 0, f"Expected exit 0: {result.output}"
    assert "Traceback" not in (result.output or "")

    # The symlink must now exist at _xdg_config_path()
    target = aws_connect._xdg_config_path()
    assert os.path.islink(target), f"Expected symlink at {target}"
    assert os.path.realpath(target) == os.path.realpath(str(linkable_source)), (
        f"Symlink target mismatch: {os.path.realpath(target)!r} != {os.path.realpath(str(linkable_source))!r}"
    )


def test_config_link_default_source(runner, aws_connect, linkable_source, monkeypatch, tmp_path):
    """config link with no argument defaults to ./environments.yaml in cwd."""
    # Place source at cwd/environments.yaml (match the default)
    cwd_file = tmp_path / "environments.yaml"
    cwd_file.write_text(linkable_source.read_text())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(aws_connect.cli, ["config", "link"])
    assert result.exit_code == 0, f"Expected exit 0 with default source: {result.output}"
    target = aws_connect._xdg_config_path()
    assert os.path.islink(target), f"Expected symlink at {target} when using default source"


def test_config_link_source_not_found(runner, aws_connect, tmp_path):
    """config link with nonexistent source exits non-zero with friendly error; no fs writes."""
    missing = str(tmp_path / "does_not_exist.yaml")
    result = runner.invoke(aws_connect.cli, ["config", "link", missing])
    assert result.exit_code != 0, "Expected non-zero exit for missing source"
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "Error" in output or "not found" in output.lower(), (
        f"Expected friendly error in output: {output!r}"
    )
    assert "Traceback" not in output, f"Traceback found: {output!r}"
    # No symlink must have been created
    target = aws_connect._xdg_config_path()
    assert not os.path.exists(target), f"Symlink must not be created for missing source: {target}"


def test_config_link_idempotent_same_symlink(runner, aws_connect, linkable_source):
    """config link called twice with the same source is idempotent; exit 0 both times."""
    result1 = runner.invoke(aws_connect.cli, ["config", "link", str(linkable_source)])
    assert result1.exit_code == 0, f"First link failed: {result1.output}"

    target = aws_connect._xdg_config_path()
    link_before = os.readlink(target)

    result2 = runner.invoke(aws_connect.cli, ["config", "link", str(linkable_source)])
    assert result2.exit_code == 0, f"Second link (idempotent) failed: {result2.output}"
    assert "Traceback" not in (result2.output or "")
    # Idempotent: the symlink must be untouched (same link target) after re-link
    assert os.readlink(target) == link_before, "Re-link must not modify the existing symlink"
    assert "Already linked" in (result2.output or ""), "Expected the idempotent no-op message"


def test_config_link_different_symlink_refuses_without_force(
    runner, aws_connect, linkable_source, tmp_path
):
    """config link refuses to replace a different-target symlink without --force; exit non-zero."""
    # Create a second source file
    other_source = tmp_path / "other.yaml"
    other_source.write_text("rds: {}\n")

    # Link to linkable_source first
    result1 = runner.invoke(aws_connect.cli, ["config", "link", str(linkable_source)])
    assert result1.exit_code == 0, result1.output

    # Try to link to other_source without --force
    result2 = runner.invoke(aws_connect.cli, ["config", "link", str(other_source)])
    assert result2.exit_code != 0, "Expected non-zero exit when replacing symlink without --force"
    output = (result2.output or "") + (result2.stderr if hasattr(result2, "stderr") and result2.stderr else "")
    assert "force" in output.lower() or "--force" in output, (
        f"Expected --force hint in error: {output!r}"
    )
    assert "Traceback" not in output
    # The original symlink must be UNCHANGED after the refusal
    target = aws_connect._xdg_config_path()
    assert os.path.realpath(target) == os.path.realpath(str(linkable_source)), (
        "Refused link must leave the original symlink pointing at linkable_source"
    )


def test_config_link_different_symlink_replaced_with_force(
    runner, aws_connect, linkable_source, tmp_path
):
    """config link --force replaces a different-target symlink; exit 0."""
    other_source = tmp_path / "other.yaml"
    other_source.write_text("rds: {}\n")

    runner.invoke(aws_connect.cli, ["config", "link", str(linkable_source)])
    result = runner.invoke(aws_connect.cli, ["config", "link", "--force", str(other_source)])
    assert result.exit_code == 0, f"Expected exit 0 with --force: {result.output}"

    target = aws_connect._xdg_config_path()
    assert os.path.realpath(target) == os.path.realpath(str(other_source)), (
        "Symlink should now point to other_source after --force"
    )


def test_config_link_real_file_refuses_without_force(runner, aws_connect, linkable_source, tmp_path):
    """config link refuses to replace a real file at the target without --force; exit non-zero."""
    # Manually plant a real file at the XDG target
    target = aws_connect._xdg_config_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write("rds: {}\n")

    result = runner.invoke(aws_connect.cli, ["config", "link", str(linkable_source)])
    assert result.exit_code != 0, "Expected non-zero exit when target is a real file without --force"
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "force" in output.lower() or "--force" in output, (
        f"Expected --force hint in error: {output!r}"
    )
    assert "Traceback" not in output
    # The real file must be UNCHANGED after the refusal (not clobbered, still a file)
    assert not os.path.islink(target), "Refused link must not turn the real file into a symlink"
    assert open(target).read() == "rds: {}\n", "Refused link must leave the real file untouched"

    # Clean up the real file (so isolate_config teardown doesn't find it)
    os.remove(target)


def test_config_link_real_file_replaced_with_force(runner, aws_connect, linkable_source, tmp_path):
    """config link --force replaces a real file at the target; exit 0 and symlink present."""
    target = aws_connect._xdg_config_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write("rds: {}\n")

    result = runner.invoke(aws_connect.cli, ["config", "link", "--force", str(linkable_source)])
    assert result.exit_code == 0, f"Expected exit 0 with --force on real file: {result.output}"
    assert os.path.islink(target), "Expected symlink after --force on real file"
    assert "Traceback" not in (result.output or "")


def test_config_link_directory_at_target_refuses(runner, aws_connect, linkable_source):
    """A directory at the XDG target is refused cleanly — no os.replace traceback (JD A-001/B-001)."""
    target = aws_connect._xdg_config_path()
    os.makedirs(target, exist_ok=True)  # the target path itself is a directory
    result = runner.invoke(aws_connect.cli, ["config", "link", "--force", str(linkable_source)])
    assert result.exit_code != 0, "Expected non-zero exit when the target is a directory"
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "Traceback" not in output, f"Traceback leaked: {output!r}"
    assert "IsADirectoryError" not in output and "NotADirectoryError" not in output, (
        f"Raw OS error leaked: {output!r}"
    )
    assert "directory" in output.lower(), f"Expected a friendly 'directory' message: {output!r}"
    os.rmdir(target)  # cleanup


def test_config_unlink_removes_symlink(runner, aws_connect, linkable_source):
    """config unlink removes an existing symlink; exit 0."""
    runner.invoke(aws_connect.cli, ["config", "link", str(linkable_source)])
    target = aws_connect._xdg_config_path()
    assert os.path.islink(target), "Pre-condition: symlink must exist before unlink"

    result = runner.invoke(aws_connect.cli, ["config", "unlink"])
    assert result.exit_code == 0, f"Expected exit 0 after unlink: {result.output}"
    # islink (not just exists): exists() follows the link and is False for a
    # dangling link even if it was NOT removed — islink pins the real behavior.
    assert not os.path.islink(target), f"Expected symlink to be removed after unlink: {target}"
    assert not os.path.exists(target), f"Expected nothing at target after unlink: {target}"
    assert "Traceback" not in (result.output or "")


def test_config_unlink_real_file_refuses(runner, aws_connect, tmp_path):
    """config unlink refuses to remove a real file at the target; exit non-zero."""
    target = aws_connect._xdg_config_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write("rds: {}\n")

    result = runner.invoke(aws_connect.cli, ["config", "unlink"])
    assert result.exit_code != 0, "Expected non-zero exit when target is a real file"
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "real file" in output or "refusing" in output.lower(), (
        f"Expected 'real file' or 'refusing' in error: {output!r}"
    )
    assert "Traceback" not in output
    # Clean up
    os.remove(target)


def test_config_unlink_absent_noop(runner, aws_connect):
    """config unlink when nothing is at the target exits 0 (no-op)."""
    result = runner.invoke(aws_connect.cli, ["config", "unlink"])
    assert result.exit_code == 0, f"Expected exit 0 for absent target: {result.output}"
    assert "Traceback" not in (result.output or "")


def test_config_link_then_get_environments(runner, aws_connect, linkable_source):
    """After config link, tier-3 discovery via get_environments finds the linked file."""
    runner.invoke(aws_connect.cli, ["config", "link", str(linkable_source)])
    # Clear cache so the next call re-resolves
    aws_connect._ENVIRONMENTS_CACHE = None
    # Suppress tier-1 and tier-2 so only tier-3 (XDG symlink) can win
    # (isolate_config already blocked tier-1 via guard path and tier-2 via empty cwd)
    envs = aws_connect.get_environments(required=False)
    assert "rds" in envs, (
        f"Expected 'rds' key discovered via tier-3 symlink, got: {envs!r}"
    )
    assert "staging" in envs.get("rds", {}), (
        f"Expected 'staging' env in 'rds', got: {envs!r}"
    )


def test_config_env_var_directory_skipped(runner, aws_connect, monkeypatch, tmp_path):
    """AWS_CONNECT_CONFIG pointing at a DIRECTORY must be skipped (isfile), not
    opened — otherwise open() raises IsADirectoryError as a raw traceback.
    With all other tiers neutralized, it falls through to the friendly error."""
    a_dir = tmp_path / "a_directory"
    a_dir.mkdir()
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(a_dir))  # a dir, not a file
    aws_connect._ENVIRONMENTS_CACHE = None

    result = runner.invoke(aws_connect.cli, ["rds", "--env", "staging"])
    assert result.exit_code != 0, "Expected non-zero exit when env var points at a directory"
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "Traceback" not in output, f"Traceback leaked: {output!r}"
    assert "IsADirectoryError" not in output, f"IsADirectoryError leaked: {output!r}"
    assert "environments.yaml" in output, f"Expected friendly missing-config error: {output!r}"
