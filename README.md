# 🚀 AWS Connection Manager

CLI tool to easily connect to AWS instances (RDS, ElastiCache, DocumentDB, EKS, OpenSearch) using SSM Session Manager.

## 📦 Installation

### Global install (recommended)

```bash
# Install as a global tool — puts aws-ssm-connect on your PATH
uv tool install .

# Reinstall after pulling or changing the code — `uv tool install` freezes a
# snapshot at install time and does NOT track your working tree, so re-run this
# to pick up new commands or fixes.
uv tool install . --reinstall

# Verify
aws-ssm-connect --help

# Sync configs with global install
aws-ssm-connect config link

# Uninstall (by the package name, not the command)
uv tool uninstall aws-ssm-connect
```

### Editable install (for development / contributors)

```bash
# Sync deps (creates .venv automatically)
uv sync

# Or with pip:
pip install -e ".[dev]"
```

### Checkout (no install)

```bash
# Install the dependencies (click, pyyaml) first
uv sync
# or: pip install click pyyaml

# Then run directly from the repo root — no install needed
uv run ./aws-ssm-connect --help
# or, with an activated environment: ./aws-ssm-connect --help
```

`aws-ssm-connect` is a thin wrapper that imports and runs the CLI defined in
`aws_connect.py`; the dependencies above are still required for it to work.

> The Usage examples below invoke `./aws-ssm-connect` directly, which assumes
> an activated environment (or a global install). In the checkout flow, prefix
> them with `uv run` — e.g. `uv run ./aws-ssm-connect list`.

## 🎯 Usage

### Available commands

```bash
# Show general help
./aws-ssm-connect --help

# List all available environments
./aws-ssm-connect list

# Connect to RDS
./aws-ssm-connect rds                    # Interactive mode
./aws-ssm-connect rds --env coffee       # Direct
./aws-ssm-connect rds --env production --local-port 5433

# Connect to Redis
./aws-ssm-connect redis                  # Interactive mode
./aws-ssm-connect redis --env coffee
./aws-ssm-connect redis --env staging-v1 --local-port 6380

# Connect to DocumentDB
./aws-ssm-connect docdb                  # Interactive mode
./aws-ssm-connect docdb --env production
./aws-ssm-connect docdb --env production --local-port 28000

# Connect to EKS
./aws-ssm-connect eks                    # Interactive mode (port forwarding only)
./aws-ssm-connect eks --env production
./aws-ssm-connect eks --env coffee --configure-kubeconfig  # Configure kubeconfig automatically

# Connect to OpenSearch
./aws-ssm-connect opensearch
./aws-ssm-connect opensearch --env coffee

# List EC2 instances
./aws-ssm-connect list-instances
./aws-ssm-connect list-instances --env coffee
```

## 📋 Examples

### Connect to RDS Coffee
```bash
./aws-ssm-connect rds --env coffee
# Will connect to localhost:5432 → RDS Coffee
```

### Connect to Redis Production on custom port
```bash
./aws-ssm-connect redis --env production --local-port 6380
# Will connect to localhost:6380 → Redis Production
```

### Connect to DocumentDB and query with mongosh
```bash
./aws-ssm-connect docdb --env production
# Will connect localhost:27017 → DocumentDB production endpoint

# In another terminal (while port forwarding is active)
mongosh --tls --tlsCAFile global-bundle.pem --host localhost --port 27017 \
  --username <user> --password <password>
```

### Connect to EKS and check nodes
```bash
# Option 1: Port forwarding only (if you already have kubeconfig configured)
./aws-ssm-connect eks --env production

# Option 2: Configure kubeconfig automatically
./aws-ssm-connect eks --env production --configure-kubeconfig

# In another terminal (while port forwarding is active)
kubectl get pods -A
```

### Connect to OpenSearch and run queries
```bash
# Start SSM session
./aws-ssm-connect opensearch --env coffee

# Inside the session, run:
curl -k https://search-coffee-esdomain-fyzljd2v5myd36hhutngya2tee.us-east-1.es.amazonaws.com/_cluster/health?pretty
```

## 🔧 Configuration

Environments are defined in `environments.yaml`, which is **committed to this
private repo** and shared across the team. It holds AWS profile names and
infrastructure identifiers (jump hosts, cluster / replication-group ids,
domains) — not credentials. `environments.yaml.example` is a reference template
documenting the schema.

To add or change an environment, edit `environments.yaml`:

```yaml
rds:
  my-environment:
    profile: my-aws-profile             # AWS CLI profile
    jumphost: My Jump Host              # EC2 jump host name
    cluster: my-cluster-name            # RDS cluster identifier (resolved at runtime)
    port: '5432'

redis:
  my-environment:
    profile: my-aws-profile
    jumphost: My Jump Host
    cluster: my-replication-group-id    # ElastiCache replication group (resolved at runtime)
    # endpoint: my-host.cache.amazonaws.com   # alternative: literal host, no AWS lookup
    port: '6379'

docdb:
  my-environment:
    profile: my-aws-profile
    jumphost: My Jump Host
    endpoint: my-cluster.cluster-xxxx.us-west-2.docdb.amazonaws.com  # literal cluster DNS endpoint
    port: '27017'
    # region: us-west-2                  # optional, defaults to us-east-1
    # warning: 'Connecting to production DocumentDB'  # optional

eks:
  my-environment:
    profile: my-k8s-profile
    jumphost: My Jump Host
    cluster: my-eks-cluster
    account_id: '123456789012'
    port: '8443'
```

Every command (`rds`, `redis`, `docdb`, `eks`, `opensearch`, `ec2`) accepts an
optional `region:` key. When set, all AWS calls for that environment (instance
lookup, endpoint resolution, SSM session) use that region instead of the
default `us-east-1`.

Keep `environments.yaml.example` updated when adding new fields or services.
Where the CLI looks for `environments.yaml` is documented in **Config discovery**
below.

## 🔧 Config discovery

The CLI searches for `environments.yaml` in this order (first match wins):

1. `$AWS_CONNECT_CONFIG` — if set and the path exists
2. `./environments.yaml` — current working directory at run time
3. `~/.config/aws-ssm-connect/environments.yaml` — XDG config dir (honors `$XDG_CONFIG_HOME`)
4. `<directory of aws_connect.py>/environments.yaml` — module-relative fallback (repo checkout)

A friendly error listing all searched locations is shown when none of the four candidates exist.

### Linking the config for a global install

When installed globally with `uv tool install .`, the tool runs from anywhere, so
tier 2 (cwd) and tier 4 (repo checkout) usually don't apply. Point tier 3 at the
repo's `environments.yaml` once, and it stays in sync with the team on every
`git pull`:

```bash
# From the repo checkout — links ~/.config/aws-ssm-connect/environments.yaml
# to ./environments.yaml
aws-ssm-connect config link

# Or link an explicit source
aws-ssm-connect config link /path/to/environments.yaml

# Remove the link
aws-ssm-connect config unlink
```

`config link` creates a **symlink** (so edits and `git pull` are reflected
immediately, no re-link). It won't overwrite a different existing link or a real
file without `--force`, and `config unlink` only removes a symlink — never a real
config file.

## 🧪 Testing

The CLI ships with a [pytest](https://docs.pytest.org/) suite built on Click's
`CliRunner`. It covers lazy config loading, `--help` and shell completion working
without an `environments.yaml`, the friendly missing/malformed-config errors,
4-tier config precedence, and behavior preservation with a valid config (AWS
calls are mocked — no real infrastructure is touched).

```bash
# Install dev dependencies
uv sync
# or: pip install -e ".[dev]"

# Run the full suite
.venv/bin/python -m pytest tests/ -v
```

> **Note:** always run the suite through this project's own `.venv`. If `pytest`
> resolves to a different project's virtualenv on your `PATH`, recreate the
> environment with the commands above.

The tests live in `tests/` (`test_cli.py` + shared fixtures in `conftest.py`) and
run entirely offline, so they are safe to wire into CI.

## 📝 Requirements

- Python 3.8+
- AWS CLI configured with the required profiles
- Session Manager Plugin installed
- kubectl (only for EKS commands)

## 🔐 Required permissions

Ensure your AWS profiles have the following permissions:
- `ec2:DescribeInstances`
- `ssm:StartSession`
- `rds:DescribeDBClusters` (for RDS)
- `eks:DescribeCluster` (for EKS)
- `es:DescribeElasticsearchDomain` (for OpenSearch)
- No extra DocumentDB IAM permission needed — `docdb` uses a literal `endpoint:` from config, no AWS API lookup

## 💡 Tips

- Port forwarding stays active until you press `Ctrl+C`
- For EKS, by default it only does port forwarding. Use `--configure-kubeconfig` if you need to configure kubectl automatically
- The Kubernetes context is named after the **profile** (not the cluster), so you can have several environments with the same cluster name without context name collisions
- Keep the session active in one terminal and use kubectl in another
- Use `--local-port` to avoid conflicts if something is already running on the default port

## 🆘 Troubleshooting

### Error: "click is not installed"
```bash
pip install click
```

### Error: "Session Manager plugin not found"
```bash
# macOS
brew install --cask session-manager-plugin

# Linux
# See: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
```

### Error: "An error occurred (InvalidInstanceId)"
Verify that:
1. The AWS profile is correct
2. The instance is in "running" state
3. SSM is enabled on the instance

## 📚 Additional documentation

[AWS SSM Port Forwarding Setup Guide](https://aws.amazon.com/es/blogs/aws/new-port-forwarding-using-aws-system-manager-sessions-manager/)
