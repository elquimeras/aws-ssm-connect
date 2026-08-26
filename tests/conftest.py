"""
Shared fixtures for aws-ssm-connect CLI tests.
"""

import inspect
import os
import sys
import textwrap
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

import aws_connect


# click < 8.2 merges stdout/stderr unless CliRunner(mix_stderr=False) is passed;
# click >= 8.2 removed `mix_stderr` entirely and always separates the streams.
# Probe the actual signature instead of parsing click.__version__ so forks/dev
# builds are handled by capability, not by a version string.
_CLIRUNNER_ACCEPTS_MIX_STDERR = (
    "mix_stderr" in inspect.signature(CliRunner.__init__).parameters
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def aws_connect():
    """Return the aws_connect module."""
    return sys.modules["aws_connect"]


@pytest.fixture
def runner():
    """Click CliRunner with stdout/stderr captured separately (spec R5).

    click 8.2 API cliff: `mix_stderr` still exists on click < 8.2 (default True,
    merging streams) but was removed on click >= 8.2, which always separates
    them. Pass mix_stderr=False only when the installed click accepts it.
    """
    if _CLIRUNNER_ACCEPTS_MIX_STDERR:
        return CliRunner(mix_stderr=False)
    return CliRunner()


@pytest.fixture(autouse=True)
def isolate_config(aws_connect, monkeypatch, tmp_path):
    """
    Isolate every test from the developer's real environments.yaml.

    Strategy (4-tier neutralization):
      - Tier 1 (env var): set AWS_CONNECT_CONFIG to a nonexistent guard path so
        the env var is present but skipped (path does not exist).
      - Tier 2 (cwd):  chdir into a fresh tmp_path with no environments.yaml.
      - Tier 3 (XDG):  point XDG_CONFIG_HOME at an empty tmp dir with no
        aws-ssm-connect subdirectory.
      - Tier 4 (module-relative): monkeypatch _module_config_path to return a
        nonexistent path inside tmp_path so the real repo environments.yaml is
        never reached.

    The memoization cache is reset before and after so no value leaks between
    tests. Fixtures like cwd_with_config override Tier 1 with their own
    monkeypatch (applied later, so they win).
    """
    # Tier 4 neutralization: redirect module-dir seam away from the real repo file
    nonexistent_module_config = str(tmp_path / "module_dir" / "environments.yaml")
    monkeypatch.setattr(aws_connect, "_module_config_path", lambda: nonexistent_module_config)

    # Tier 1: env var guard (nonexistent path — skipped by resolver)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(tmp_path / "guard_environments.yaml"))

    # Tier 2: chdir into empty tmp_path (no environments.yaml there)
    monkeypatch.chdir(tmp_path)

    # Tier 3: point XDG_CONFIG_HOME at an empty tmp dir
    xdg_empty = str(tmp_path / "xdg_empty")
    os.makedirs(xdg_empty, exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", xdg_empty)

    # Reset cache before test
    aws_connect._ENVIRONMENTS_CACHE = None
    yield
    # Reset cache after test
    aws_connect._ENVIRONMENTS_CACHE = None


@pytest.fixture
def cwd_no_config(aws_connect, monkeypatch, tmp_path):
    """
    Ensure the module behaves as if environments.yaml is absent.

    isolate_config already guarantees all 4 tiers are blocked, so this fixture
    is now a no-op — it exists to make existing test signatures work unchanged.
    The guard env var set by isolate_config points at a nonexistent path, so
    get_environments() will raise ConfigMissingError correctly.
    """
    # Reinforce Tier 1 with an explicit nonexistent path (redundant but explicit)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(tmp_path / "nonexistent_environments.yaml"))


@pytest.fixture
def cwd_with_config(aws_connect, monkeypatch, tmp_path):
    """
    Write a minimal valid environments.yaml to a temp directory and set
    AWS_CONNECT_CONFIG to point at it.  Returns the path for tests that need it.
    """
    config = textwrap.dedent("""\
        rds:
          staging:
            profile: my-profile
            jumphost: my-jumphost
            cluster: my-cluster
            port: '5432'
          prod:
            profile: my-profile
            jumphost: my-jumphost
            cluster: my-cluster-prod
            port: '5432'
        redis:
          staging:
            profile: my-profile
            jumphost: my-jumphost
            endpoint: my-endpoint.cache.amazonaws.com
            port: '6379'
        eks:
          staging:
            profile: my-profile
            jumphost: my-jumphost
            cluster: my-eks-cluster
            port: '8443'
        opensearch:
          staging:
            profile: my-profile
            jumphost: my-jumphost
            domain: my-domain
        ec2:
          staging:
            profile: my-profile
            jumphost: my-jumphost
    """)
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(config)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def cwd_config_no_ec2(aws_connect, monkeypatch, tmp_path):
    """
    Valid config that intentionally omits the 'ec2' section, to exercise the
    "no 'ec2' configuration" error path in jumphost / list-instances.
    """
    config = textwrap.dedent("""\
        rds:
          staging:
            profile: my-profile
            jumphost: my-jumphost
            cluster: my-cluster
            port: '5432'
    """)
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(config)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def cwd_malformed_config(aws_connect, monkeypatch, tmp_path):
    """
    Write syntactically invalid YAML to a temp file and set AWS_CONNECT_CONFIG
    so the module tries (and fails gracefully) to parse it.
    """
    bad_yaml = "rds:\n  - this: is\n  bad yaml: [\n"
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(bad_yaml)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def mock_subprocess(aws_connect, monkeypatch):
    """
    Patch os.system and aws_connect.run_command so that no real subprocess is
    started during tests.  os.system returns 0 (success); run_command returns
    ('', 0).
    """
    mock_os_system = MagicMock(return_value=0)
    monkeypatch.setattr("os.system", mock_os_system)
    monkeypatch.setattr(aws_connect, "run_command", MagicMock(return_value=("fake-id", 0)))
    return mock_os_system


# ---------------------------------------------------------------------------
# Redis endpoint-resolution fixtures (redis-endpoint-resolution change)
# ---------------------------------------------------------------------------

import json as _json


@pytest.fixture
def cwd_with_redis_cluster_config(aws_connect, monkeypatch, tmp_path):
    """
    Config with a redis env that uses `cluster` (no `endpoint`).
    Used to verify AWS-resolution path.
    """
    config = textwrap.dedent("""\
        redis:
          cluster-env:
            profile: my-profile
            jumphost: my-jumphost
            cluster: my-replication-group
            port: '6379'
    """)
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(config)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def cwd_with_redis_bare_config(aws_connect, monkeypatch, tmp_path):
    """
    Config with a redis env that has neither `cluster` nor `endpoint`.
    Used to verify the friendly error path.
    """
    config = textwrap.dedent("""\
        redis:
          bare-env:
            profile: my-profile
            jumphost: my-jumphost
            port: '6379'
    """)
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(config)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def mock_subprocess_elasticache_primary(aws_connect, monkeypatch):
    """
    Patch run_command with side_effect ordered as:
      call 1 — get_instance_id  -> ("fake-instance-id", 0)
      call 2 — get_redis_endpoint -> JSON with PrimaryEndpoint.Address set
    Also patches os.system to capture the SSM command.
    """
    _primary_json = _json.dumps({
        "NodeGroups": [
            {
                "PrimaryEndpoint": {"Address": "primary.cache.example.com", "Port": 6379},
                "NodeGroupId": "0001",
            }
        ],
        "ConfigurationEndpoint": None,
    })
    mock_run = MagicMock(side_effect=[
        ("fake-instance-id", 0),
        (_primary_json, 0),
    ])
    mock_os_system = MagicMock(return_value=0)
    monkeypatch.setattr(aws_connect, "run_command", mock_run)
    monkeypatch.setattr("os.system", mock_os_system)
    return mock_os_system, mock_run


@pytest.fixture
def mock_subprocess_elasticache_config_ep(aws_connect, monkeypatch):
    """
    Patch run_command with side_effect ordered as:
      call 1 — get_instance_id  -> ("fake-instance-id", 0)
      call 2 — get_redis_endpoint -> JSON with PrimaryEndpoint null, ConfigurationEndpoint set
    """
    _config_json = _json.dumps({
        "NodeGroups": [
            {
                "PrimaryEndpoint": None,
                "NodeGroupId": "0001",
            }
        ],
        "ConfigurationEndpoint": {"Address": "config.cache.example.com", "Port": 6379},
    })
    mock_run = MagicMock(side_effect=[
        ("fake-instance-id", 0),
        (_config_json, 0),
    ])
    mock_os_system = MagicMock(return_value=0)
    monkeypatch.setattr(aws_connect, "run_command", mock_run)
    monkeypatch.setattr("os.system", mock_os_system)
    return mock_os_system, mock_run


@pytest.fixture
def mock_subprocess_elasticache_failure(aws_connect, monkeypatch):
    """
    Patch run_command with side_effect ordered as:
      call 1 — get_instance_id  -> ("fake-instance-id", 0)
      call 2 — get_redis_endpoint -> ("", 1)  [AWS lookup failure]
    """
    mock_run = MagicMock(side_effect=[
        ("fake-instance-id", 0),
        ("", 1),
    ])
    mock_os_system = MagicMock(return_value=0)
    monkeypatch.setattr(aws_connect, "run_command", mock_run)
    monkeypatch.setattr("os.system", mock_os_system)
    return mock_os_system, mock_run


@pytest.fixture
def linkable_source(aws_connect, tmp_path):
    """
    Create a minimal valid environments.yaml source file inside the XDG-isolated
    tmp_path (set by the autouse isolate_config fixture).  The file lives at
    tmp_path/source/environments.yaml so it is distinct from the XDG target
    directory tree also rooted in tmp_path.

    Returns the pathlib.Path to the source file.

    NOTE: isolate_config (autouse) already points XDG_CONFIG_HOME to
    tmp_path/xdg_empty.  This fixture does NOT override XDG_CONFIG_HOME — it
    relies on that isolation so that _xdg_config_path() resolves inside tmp_path
    and the test never touches ~/.config.
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_file = source_dir / "environments.yaml"
    source_file.write_text(
        "rds:\n"
        "  staging:\n"
        "    profile: link-profile\n"
        "    jumphost: link-jumphost\n"
        "    cluster: link-cluster\n"
        "    port: '5432'\n"
    )
    return source_file


@pytest.fixture
def cwd_with_region_config(aws_connect, monkeypatch, tmp_path):
    """
    Config with a redis env that sets an explicit `region: us-west-2`, used to
    verify the region override is threaded into lookup + SSM commands.
    """
    config = textwrap.dedent("""\
        redis:
          region-env:
            profile: my-profile
            jumphost: my-jumphost
            endpoint: my-endpoint.cache.amazonaws.com
            port: '6379'
            region: us-west-2
    """)
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(config)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def cwd_with_docdb_config(aws_connect, monkeypatch, tmp_path):
    """
    Config with a docdb env: literal endpoint, region override, and warning.
    """
    config = textwrap.dedent("""\
        docdb:
          production:
            profile: my-profile
            jumphost: my-jumphost
            endpoint: my-docdb-cluster.cluster-xxxx.us-west-2.docdb.amazonaws.com
            port: '27017'
            region: us-west-2
            warning: 'Connecting to production DocumentDB'
    """)
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(config)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def cwd_with_docdb_bare_config(aws_connect, monkeypatch, tmp_path):
    """
    Config with a docdb env that has no `endpoint` key — friendly error path.
    """
    config = textwrap.dedent("""\
        docdb:
          bare-env:
            profile: my-profile
            jumphost: my-jumphost
            port: '27017'
    """)
    config_file = tmp_path / "environments.yaml"
    config_file.write_text(config)
    monkeypatch.setenv("AWS_CONNECT_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def mock_subprocess_elasticache_null(aws_connect, monkeypatch):
    """
    Patch run_command with side_effect ordered as:
      call 1 — get_instance_id  -> ("fake-instance-id", 0)
      call 2 — get_redis_endpoint -> ("null", 0)  [AWS query matched no group;
               `aws ... --query 'ReplicationGroups[0]'` prints the JSON literal
               `null` with a zero exit code]
    """
    mock_run = MagicMock(side_effect=[
        ("fake-instance-id", 0),
        ("null", 0),
    ])
    mock_os_system = MagicMock(return_value=0)
    monkeypatch.setattr(aws_connect, "run_command", mock_run)
    monkeypatch.setattr("os.system", mock_os_system)
    return mock_os_system, mock_run
