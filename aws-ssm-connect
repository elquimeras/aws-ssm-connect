#!/usr/bin/env python3
"""
AWS Connection Manager CLI
Tool to connect easily to AWS instances (RDS, ElastiCache, DocumentDB, EKS, OpenSearch)
"""

import subprocess
import sys
import os
import json

try:
    import click
    import yaml
except ImportError as e:
    missing_package = str(e).split("'")[1]
    print(f"❌ Error: '{missing_package}' is not installed.")
    print("Install with: pip install . (or: uv tool install .)")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration — lazy-loaded, memoized
# ---------------------------------------------------------------------------

_ENVIRONMENTS_CACHE = None


def _module_config_path():
    """Return the module-relative environments.yaml candidate (tier-4 fallback).

    Isolated in its own function so that tests can monkeypatch this seam to a
    nonexistent path, preventing the real repo file from being read when all
    other tiers are suppressed.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "environments.yaml")


def _xdg_config_path():
    """Return the XDG-compliant config path for environments.yaml.

    Respects $XDG_CONFIG_HOME when set; falls back to ~/.config otherwise.
    """
    xdg_base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(xdg_base, "aws-ssm-connect", "environments.yaml")


def _resolve_config_path():
    """Return the first existing config path by 4-tier precedence, else None.

    Tiers evaluated at call time (never cached here; memoization lives in
    get_environments):
      1. $AWS_CONNECT_CONFIG  — used only when the path actually exists on disk
      2. ./environments.yaml  — current working directory at call time
      3. $XDG_CONFIG_HOME/aws-ssm-connect/environments.yaml  (or ~/.config/...)
      4. <dir of aws_connect.py>/environments.yaml  (module-relative fallback)
    """
    # Each candidate must be a regular file: os.path.isfile() (not exists())
    # so a path pointing at a directory is skipped instead of later blowing up
    # in open() with an IsADirectoryError traceback.

    # Tier 1: explicit env var
    override = os.environ.get("AWS_CONNECT_CONFIG")
    if override and os.path.isfile(override):
        return override

    # Tier 2: cwd
    cwd_candidate = os.path.join(os.getcwd(), "environments.yaml")
    if os.path.isfile(cwd_candidate):
        return cwd_candidate

    # Tier 3: XDG / ~/.config
    xdg_candidate = _xdg_config_path()
    if os.path.isfile(xdg_candidate):
        return xdg_candidate

    # Tier 4: module-relative (monkeypatchable via _module_config_path)
    module_candidate = _module_config_path()
    if os.path.isfile(module_candidate):
        return module_candidate

    return None


class ConfigMissingError(click.ClickException):
    exit_code = 1

    def format_message(self):
        xdg_path = _xdg_config_path()
        return (
            "environments.yaml not found.\n\n"
            "Searched locations (in order):\n"
            "  1. $AWS_CONNECT_CONFIG environment variable\n"
            "  2. ./environments.yaml (current working directory)\n"
            f"  3. {xdg_path}\n"
            "  4. <directory of aws_connect.py>/environments.yaml\n\n"
            "To get started, copy the example:\n"
            "  cp environments.yaml.example environments.yaml"
        )


class ConfigMalformedError(click.ClickException):
    exit_code = 1

    def format_message(self):
        return "environments.yaml is not valid YAML and could not be parsed."


def get_environments(required=True):
    """
    Return the parsed environments dict, memoized after the first successful
    read.  When `required` is True a missing or malformed file raises a
    ClickException (friendly error, no traceback).  When `required` is False
    both cases return {} silently (used by shell-completion callbacks).
    """
    global _ENVIRONMENTS_CACHE
    if _ENVIRONMENTS_CACHE is not None:
        return _ENVIRONMENTS_CACHE

    config_path = _resolve_config_path()

    if config_path is None:
        if required:
            raise ConfigMissingError("")
        return {}

    try:
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        if required:
            raise ConfigMalformedError("")
        return {}
    except OSError as e:
        # Path passed isfile() but could not be read (permissions, stale mount,
        # a race, ...). Surface a friendly error rather than a raw traceback.
        if required:
            raise click.ClickException(f"Could not read {config_path}: {e}")
        return {}

    _ENVIRONMENTS_CACHE = data
    return _ENVIRONMENTS_CACHE


def _complete_env(service):
    """
    Return a Click shell_complete callback that suggests environment names for
    the given service section.  Returns [] silently when the config is absent
    or malformed.
    """
    def _cb(ctx, param, incomplete):
        envs = get_environments(required=False).get(service, {})
        return [k for k in envs if k.startswith(incomplete)]
    return _cb


def _prompt_env(service, env, environments):
    """
    When --env was not supplied on the command line, prompt interactively while
    showing the available environments for the service (e.g. ``Environment
    (coffee, production, staging):``).  Config is already loaded lazily by the
    caller, so this keeps the choice list in the prompt without reintroducing an
    import-time dependency on the config file.
    """
    if env is not None:
        return env
    choices = sorted(environments.get(service, {}).keys())
    if not choices:
        click.echo(f"❌ Error: No '{service}' environments defined in environments.yaml", err=True)
        sys.exit(1)
    return click.prompt('Environment', type=click.Choice(choices))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_REGION = 'us-east-1'


def _region(config):
    """Return the per-environment region override, or DEFAULT_REGION.

    Treats an absent key, `None`, and an empty string identically as "unset".
    """
    return str(config.get('region') or DEFAULT_REGION)


def run_command(cmd, env=None):
    """Run a command and return the output"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            env=env or os.environ.copy()
        )
        return result.stdout.strip(), result.returncode
    except Exception as e:
        return str(e), 1


def get_instance_id(profile, jumphost_name, region=DEFAULT_REGION):
    """Get the jumphost Instance ID"""
    click.echo(f"🔍 Looking up jumphost '{jumphost_name}'...")

    cmd = f"""aws ec2 describe-instances \
        --profile {profile} \
        --region {region} \
        --filters "Name=instance-state-name,Values=running" \
                  "Name=tag:Name,Values={jumphost_name}" \
        --query "Reservations[*].Instances[*].InstanceId" \
        --output text"""

    output, code = run_command(cmd)

    if code != 0 or not output:
        click.echo(f"❌ Error getting Instance ID: {output}", err=True)
        sys.exit(1)

    click.echo(f"✅ Instance ID: {output}")
    return output


def get_rds_endpoint(profile, cluster_name, region=DEFAULT_REGION):
    """Get the RDS cluster endpoint"""
    click.echo(f"🔍 Getting RDS cluster endpoint '{cluster_name}'...")

    cmd = f"""aws rds describe-db-clusters \
        --profile {profile} \
        --region {region} \
        --db-cluster-identifier {cluster_name} \
        --query 'DBClusters[0].Endpoint' \
        --output text"""

    output, code = run_command(cmd)

    if code != 0 or not output:
        click.echo(f"❌ Error getting RDS endpoint: {output}", err=True)
        sys.exit(1)

    click.echo(f"✅ RDS Endpoint: {output}")
    return output


def get_redis_endpoint(profile, replication_group, region=DEFAULT_REGION):
    """Get the ElastiCache primary (or configuration) endpoint."""
    click.echo(f"🔍 Getting Redis endpoint '{replication_group}'...")

    cmd = f"""aws elasticache describe-replication-groups \
        --profile {profile} \
        --region {region} \
        --replication-group-id {replication_group} \
        --query 'ReplicationGroups[0]' \
        --output json"""

    output, code = run_command(cmd)

    if code != 0 or not output:
        click.echo(f"❌ Error getting Redis endpoint: {output}", err=True)
        sys.exit(1)

    try:
        rg = json.loads(output) or {}
    except (ValueError, TypeError):
        click.echo(f"❌ Error getting Redis endpoint: {output}", err=True)
        sys.exit(1)

    # `rg` is now always a dict: an AWS query matching no group returns the JSON
    # literal `null`, which json.loads() parses to None -> normalized to {} above.
    node_groups = rg.get('NodeGroups') or [{}]
    primary = (node_groups[0].get('PrimaryEndpoint') or {}).get('Address')
    config_ep = (rg.get('ConfigurationEndpoint') or {}).get('Address')
    endpoint = primary or config_ep

    if not endpoint:
        click.echo(f"❌ Error getting Redis endpoint: {output}", err=True)
        sys.exit(1)

    click.echo(f"✅ Redis Endpoint: {endpoint}")
    return endpoint


def get_eks_endpoint(profile, cluster_name, region=DEFAULT_REGION):
    """Get the EKS cluster endpoint"""
    click.echo(f"🔍 Getting EKS cluster endpoint '{cluster_name}'...")

    cmd = f"""aws eks describe-cluster \
        --profile {profile} \
        --region {region} \
        --name {cluster_name} \
        --query 'cluster.endpoint' \
        --output text | sed 's|https://||'"""

    output, code = run_command(cmd)

    if code != 0 or not output:
        click.echo(f"❌ Error getting EKS endpoint: {output}", err=True)
        sys.exit(1)

    click.echo(f"✅ EKS Endpoint: {output}")
    return output


def get_opensearch_endpoint(profile, domain_name, region=DEFAULT_REGION):
    """Get the OpenSearch domain endpoint"""
    click.echo(f"🔍 Getting OpenSearch domain endpoint '{domain_name}'...")
    cmd = f"""aws opensearch describe-domain \
        --profile {profile} \
        --region {region} \
        --domain-name {domain_name} \
        --query 'DomainStatus.Endpoint' \
        --output text"""
    output, code = run_command(cmd)
    if code != 0 or not output:
        click.echo(f"❌ Error getting OpenSearch endpoint: {output}", err=True)
        sys.exit(1)
    click.echo(f"✅ OpenSearch Endpoint: {output}")
    return output.strip()


def get_account_id(profile):
    """Get account ID from profile (STS GetCallerIdentity)"""
    cmd = f"""aws sts get-caller-identity \
        --profile {profile} \
        --query Account \
        --output text"""
    output, code = run_command(cmd)
    if code != 0 or not output:
        click.echo(f"❌ Error getting account ID: {output}", err=True)
        sys.exit(1)
    return output.strip()


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """🚀 AWS Connection Manager - Connect easily to your AWS instances"""
    pass


@cli.command()
@click.option('--env', shell_complete=_complete_env('rds'),
              help='Environment to connect to')
@click.option('--local-port', default='5432', help='Local port (default: 5432)')
def rds(env, local_port):
    """📦 Connect to RDS (PostgreSQL)"""
    environments = get_environments()
    env = _prompt_env('rds', env, environments)
    if 'rds' not in environments or env not in environments['rds']:
        available = ', '.join(environments.get('rds', {}).keys()) or '(none)'
        click.echo(f"❌ Error: Environment 'rds.{env}' not found in environments.yaml", err=True)
        click.echo(f"   Available environments: {available}", err=True)
        sys.exit(1)
    config = environments['rds'][env]
    region = _region(config)

    click.echo(f"\n🎯 Connecting to RDS {env.upper()}")
    click.echo(f"   Profile: {config['profile']}")
    click.echo(f"   Local port: {local_port}\n")

    # Get Instance ID
    instance_id = get_instance_id(config['profile'], config['jumphost'], region=region)

    # Get RDS Endpoint
    profile_cluster = config.get('profile_cluster', config['profile'])
    rds_endpoint = get_rds_endpoint(profile_cluster, config['cluster'], region=region)

    # Comando de conexión
    cmd = f"""aws ssm start-session \
        --profile {config['profile']} \
        --region {region} \
        --target {instance_id} \
        --document-name AWS-StartPortForwardingSessionToRemoteHost \
        --parameters host="{rds_endpoint}",portNumber="{config['port']}",localPortNumber="{local_port}" """

    click.echo(f"\n🔌 Starting port forwarding...")
    click.echo(f"   localhost:{local_port} → {rds_endpoint}:{config['port']}\n")

    # Run interactive command
    os.system(cmd)


@cli.command()
@click.option('--env', shell_complete=_complete_env('redis'),
              help='Environment to connect to')
@click.option('--local-port', default='6379', help='Local port (default: 6379)')
def redis(env, local_port):
    """🔴 Connect to ElastiCache (Redis)"""
    environments = get_environments()
    env = _prompt_env('redis', env, environments)
    if 'redis' not in environments or env not in environments['redis']:
        available = ', '.join(environments.get('redis', {}).keys()) or '(none)'
        click.echo(f"❌ Error: Environment 'redis.{env}' not found in environments.yaml", err=True)
        click.echo(f"   Available environments: {available}", err=True)
        sys.exit(1)
    config = environments['redis'][env]
    region = _region(config)

    if 'warning' in config:
        click.echo(f"\n{config['warning']}\n")

    click.echo(f"\n🎯 Connecting to Redis {env.upper()}")
    click.echo(f"   Profile: {config['profile']}")
    click.echo(f"   Local port: {local_port}\n")

    # Get Instance ID
    instance_id = get_instance_id(config['profile'], config['jumphost'], region=region)

    # Resolve remote host — cluster (AWS lookup) takes precedence over endpoint (literal)
    if config.get('cluster'):
        profile_cluster = config.get('profile_cluster', config['profile'])
        redis_endpoint = get_redis_endpoint(profile_cluster, config['cluster'], region=region)
    elif config.get('endpoint'):
        redis_endpoint = config['endpoint']
    else:
        click.echo(
            f"❌ Error: Environment 'redis.{env}' has no 'cluster' or 'endpoint' "
            f"in environments.yaml",
            err=True,
        )
        sys.exit(1)

    # Connection command
    cmd = f"""aws ssm start-session \
        --profile {config['profile']} \
        --region {region} \
        --target {instance_id} \
        --document-name AWS-StartPortForwardingSessionToRemoteHost \
        --parameters host="{redis_endpoint}",portNumber="{config['port']}",localPortNumber="{local_port}" """

    click.echo(f"\n🔌 Starting port forwarding...")
    click.echo(f"   localhost:{local_port} → {redis_endpoint}:{config['port']}\n")

    # Run interactive command
    os.system(cmd)


@cli.command()
@click.option('--env', shell_complete=_complete_env('docdb'),
              help='Environment to connect to')
@click.option('--local-port', default=None, help='Local port (default: port from environment in environments.yaml)')
def docdb(env, local_port):
    """🍃 Connect to DocumentDB (port forwarding)"""
    environments = get_environments()
    env = _prompt_env('docdb', env, environments)
    if 'docdb' not in environments or env not in environments['docdb']:
        available = ', '.join(environments.get('docdb', {}).keys()) or '(none)'
        click.echo(f"❌ Error: Environment 'docdb.{env}' not found in environments.yaml", err=True)
        click.echo(f"   Available environments: {available}", err=True)
        sys.exit(1)
    config = environments['docdb'][env]
    region = _region(config)

    if not config.get('endpoint'):
        click.echo(
            f"❌ Error: Environment 'docdb.{env}' has no 'endpoint' in environments.yaml",
            err=True,
        )
        sys.exit(1)

    if 'warning' in config:
        click.echo(f"\n{config['warning']}\n")

    remote_port = str(config.get('port', '27017'))
    local_port = str(local_port or remote_port)
    docdb_endpoint = config['endpoint']

    click.echo(f"\n🎯 Connecting to DocumentDB {env.upper()}")
    click.echo(f"   Profile: {config['profile']}")
    click.echo(f"   Local port: {local_port}\n")

    # Get Instance ID
    instance_id = get_instance_id(config['profile'], config['jumphost'], region=region)

    # Connection command
    cmd = f"""aws ssm start-session \
        --profile {config['profile']} \
        --region {region} \
        --target {instance_id} \
        --document-name AWS-StartPortForwardingSessionToRemoteHost \
        --parameters host="{docdb_endpoint}",portNumber="{remote_port}",localPortNumber="{local_port}" """

    click.echo(f"\n🔌 Starting port forwarding...")
    click.echo(f"   localhost:{local_port} → {docdb_endpoint}:{remote_port}\n")

    # Run interactive command
    os.system(cmd)


@cli.command()
@click.option('--env', shell_complete=_complete_env('eks'),
              help='Environment to connect to')
@click.option('--local-port', default=None, help='Local port (default: port from environment in environments.yaml)')
@click.option('--configure-kubeconfig', is_flag=True, help='Configure kubeconfig automatically')
def eks(env, local_port, configure_kubeconfig):
    """☸️  Connect to EKS (Kubernetes)"""
    environments = get_environments()
    env = _prompt_env('eks', env, environments)
    if 'eks' not in environments or env not in environments['eks']:
        available = ', '.join(environments.get('eks', {}).keys()) or '(none)'
        click.echo(f"❌ Error: Environment 'eks.{env}' not found in environments.yaml", err=True)
        click.echo(f"   Available environments: {available}", err=True)
        sys.exit(1)
    config = environments['eks'][env]
    region = _region(config)
    local_port = str(local_port or config.get('port', '8443'))

    click.echo(f"\n🎯 Connecting to EKS {env.upper()}")
    click.echo(f"   Profile: {config['profile']}")
    click.echo(f"   Cluster: {config['cluster']}")
    click.echo(f"   Local port: {local_port}\n")

    # Get Instance ID
    instance_id = get_instance_id(config['profile'], config['jumphost'], region=region)

    # Get EKS Endpoint
    eks_endpoint = get_eks_endpoint(config['profile'], config['cluster'], region=region)

    # Configure kubeconfig if requested (context name = profile to avoid collisions when cluster names repeat)
    if configure_kubeconfig:
        kube_context = config['profile']
        click.echo(f"\n⚙️  Configuring kubeconfig (context: {kube_context})...")
        account_id = config.get('account_id') or get_account_id(config['profile'])

        # Update kubeconfig: use profile as context alias so contexts are unique across environments
        cmd_update = f"""aws eks update-kubeconfig \
            --profile {config['profile']} \
            --region {region} \
            --name {config['cluster']} \
            --alias {kube_context}"""

        os.system(cmd_update)

        # Set cluster server
        cmd_set_cluster = f"""kubectl config set-cluster arn:aws:eks:{region}:{account_id}:cluster/{config['cluster']} \
            --server=https://localhost:{local_port} \
            --insecure-skip-tls-verify=true"""

        os.system(cmd_set_cluster)

        # Use context (named by profile)
        cmd_use_context = f"kubectl config use-context {kube_context}"
        os.system(cmd_use_context)

        click.echo(f"✅ Kubeconfig configured\n")

    # Connection command
    cmd = f"""aws ssm start-session \
        --profile {config['profile']} \
        --region {region} \
        --target {instance_id} \
        --document-name AWS-StartPortForwardingSessionToRemoteHost \
        --parameters host="{eks_endpoint}",portNumber="443",localPortNumber="{local_port}" """

    click.echo(f"\n🔌 Starting port forwarding...")
    click.echo(f"   localhost:{local_port} → {eks_endpoint}:443\n")
    click.echo(f"💡 Tip: In a new terminal run: kubectl config use-context {config['profile']}\n")
    click.echo(f"💡 Tip: You can now use kubectl (e.g. kubectl get pods -A)\n")

    # Run interactive command
    os.system(cmd)


@cli.command()
@click.option('--env', shell_complete=_complete_env('opensearch'),
              help='Environment to connect to')
def opensearch(env):
    """🔍 Connect to OpenSearch (direct SSM session)"""
    environments = get_environments()
    env = _prompt_env('opensearch', env, environments)
    if 'opensearch' not in environments or env not in environments['opensearch']:
        available = ', '.join(environments.get('opensearch', {}).keys()) or '(none)'
        click.echo(f"❌ Error: Environment 'opensearch.{env}' not found in environments.yaml", err=True)
        click.echo(f"   Available environments: {available}", err=True)
        sys.exit(1)
    config = environments['opensearch'][env]
    region = _region(config)

    click.echo(f"\n🎯 Connecting to OpenSearch {env.upper()}")
    click.echo(f"   Profile: {config['profile']}\n")

    # Get Instance ID
    instance_id = get_instance_id(config['profile'], config['jumphost'], region=region)

    # Get OpenSearch endpoint
    opensearch_endpoint = get_opensearch_endpoint(config['profile'], config['domain'], region=region)

    # Connection command
    cmd = f"""aws ssm start-session \
        --profile {config['profile']} \
        --region {region} \
        --target {instance_id}"""

    click.echo(f"\n🔌 Starting SSM session...")
    click.echo(f"\n💡 Tip: Once connected, you can use awscurl (same profile):")
    click.echo(f"   awscurl --service es -X GET \"https://{opensearch_endpoint}/_cluster/health?pretty\" --profile {config['profile']}\n")

    # Run interactive command
    os.system(cmd)


@cli.command()
@click.option('--env', shell_complete=_complete_env('ec2'),
              help='Environment to connect to')
def jumphost(env):
    """🖥️  Connect to the jumphost (bash session on the instance)"""
    environments = get_environments()
    env = _prompt_env('ec2', env, environments)
    if 'ec2' not in environments:
        click.echo("❌ Error: No 'ec2' configuration in environments.yaml", err=True)
        click.echo("   Add an 'ec2' section with your environments", err=True)
        sys.exit(1)

    if env not in environments['ec2']:
        available = ', '.join(environments['ec2'].keys())
        click.echo(f"❌ Error: Environment '{env}' not found in 'ec2'", err=True)
        click.echo(f"   Available environments: {available}", err=True)
        sys.exit(1)

    config = environments['ec2'][env]
    if 'jumphost' not in config:
        click.echo(f"❌ Error: Environment 'ec2.{env}' has no 'jumphost' in environments.yaml", err=True)
        sys.exit(1)

    click.echo(f"\n🎯 Connecting to EC2 {env.upper()}")
    click.echo(f"   Profile: {config['profile']}")
    click.echo(f"   Jumphost: {config['jumphost']}\n")

    region = _region(config)
    instance_id = get_instance_id(config['profile'], config['jumphost'], region=region)

    cmd = f"""aws ssm start-session \
        --profile {config['profile']} \
        --region {region} \
        --target {instance_id}"""

    click.echo("\n🔌 Starting SSM session (bash on instance)...\n")

    os.system(cmd)


@cli.command()
def list():
    """📋 List all available environments"""
    environments = get_environments()
    click.echo("\n📋 Available environments:\n")

    for service, envs in environments.items():
        click.echo(f"🔹 {service.upper()}:")
        for env_name in envs.keys():
            click.echo(f"   • {env_name}")
        click.echo()


@cli.command()
@click.option('--env', prompt='Environment', help='Environment to use')
def list_instances(env):
    """🖥️  List running EC2 instances for the environment"""
    environments = get_environments()

    # Validate ec2 exists in config
    if 'ec2' not in environments:
        click.echo(f"❌ Error: No 'ec2' configuration in environments.yaml", err=True)
        click.echo("   Add an 'ec2' section with your environments", err=True)
        sys.exit(1)

    if env not in environments['ec2']:
        available = ', '.join(environments['ec2'].keys())
        click.echo(f"❌ Error: Environment '{env}' not found in 'ec2'", err=True)
        click.echo(f"   Available environments: {available}", err=True)
        sys.exit(1)

    config = environments['ec2'][env]
    profile = config['profile']
    region = _region(config)

    click.echo(f"\n🔍 Listing EC2 instances")
    click.echo(f"   Environment: {env.upper()}")
    click.echo(f"   Profile: {profile}\n")

    cmd = f"""aws ec2 describe-instances \
        --profile {profile} \
        --region {region} \
        --filters "Name=instance-state-name,Values=running" \
        --query "Reservations[*].Instances[*].[InstanceId,Tags[?Key=='Name'].Value|[0]]" \
        --output table"""

    os.system(cmd)


@cli.group()
def config():
    """Manage the environments.yaml config link"""
    pass


@config.command('link')
@click.argument('source', required=False, default='./environments.yaml')
@click.option('--force', is_flag=True, help='Replace an existing file or different symlink')
def config_link(source, force):
    """Link a source environments.yaml into the XDG config directory."""
    source_abs = os.path.abspath(source)
    if not os.path.isfile(source_abs):
        click.echo(f"❌ Error: source file not found: {source_abs}", err=True)
        sys.exit(1)
    target = _xdg_config_path()
    if os.path.islink(target):
        if os.path.realpath(target) == os.path.realpath(source_abs):
            click.echo(f"✅ Already linked: {target} -> {source_abs}")
            return
        if not force:
            click.echo(f"❌ Error: {target} already links elsewhere. Use --force to replace.", err=True)
            sys.exit(1)
    elif os.path.isdir(target):
        # A directory can't be atomically swapped for a symlink; refuse clearly
        # (even with --force) rather than letting os.replace raise a traceback.
        click.echo(f"❌ Error: {target} is a directory; refusing to replace it.", err=True)
        sys.exit(1)
    elif os.path.exists(target):
        if not force:
            click.echo(f"❌ Error: {target} is a real file. Use --force to replace.", err=True)
            sys.exit(1)
    # Create the link atomically: symlink a temp name then os.replace it into
    # place. A --force replacement therefore never leaves the target missing if
    # something fails partway — the old target stays until the atomic swap.
    tmp_link = f"{target}.tmp-{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.islink(tmp_link) or os.path.exists(tmp_link):
            os.remove(tmp_link)
        os.symlink(source_abs, tmp_link)
        os.replace(tmp_link, target)
    except OSError as e:
        # Best-effort temp cleanup, then a friendly error (no raw traceback).
        try:
            if os.path.islink(tmp_link) or os.path.exists(tmp_link):
                os.remove(tmp_link)
        except OSError:
            pass
        click.echo(f"❌ Error: could not create link at {target}: {e}", err=True)
        sys.exit(1)
    click.echo(f"✅ Linked {target} -> {source_abs}")


@config.command('unlink')
def config_unlink():
    """Remove the symlink from the XDG config directory."""
    target = _xdg_config_path()
    if os.path.islink(target):
        try:
            os.remove(target)
        except OSError as e:
            click.echo(f"❌ Error: could not remove {target}: {e}", err=True)
            sys.exit(1)
        click.echo(f"✅ Unlinked {target}")
    elif os.path.exists(target):
        click.echo(f"❌ Error: {target} is a real file, not a symlink; refusing to remove.", err=True)
        sys.exit(1)
    else:
        click.echo(f"ℹ️  Nothing to unlink at {target}")


# Command order for --help
_COMMAND_ORDER = ['list', 'list-instances', 'jumphost', 'rds', 'redis', 'docdb', 'opensearch', 'eks', 'config']


def _list_commands(ctx):
    return [c for c in _COMMAND_ORDER if c in cli.commands]


cli.list_commands = _list_commands


if __name__ == '__main__':
    cli()
