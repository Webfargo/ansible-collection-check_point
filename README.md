# Ansible Collection: webfargo.check_point

Ansible modules for managing Check Point Gaia OS infrastructure:
- Deployment Agent package operations
- System facts gathering (gather_facts)

## Requirements

- Ansible 2.15+
- Python 3.9+ on control node
- Python 3.x on managed Check Point hosts (typically symlinked at `/usr/bin/python3`)
- SSH access to managed hosts

## Compatibility

| Check Point Version | ansible-core | ansible (community) |
|---------------------|--------------|---------------------|
| R81.20 and earlier  | ≤ 2.16       | ≤ 9.x               |
| R82 and later       | ≥ 2.17       | ≥ 10.x              |

> **Note:** This collection connects to Check Point hosts via SSH and executes
> commands using the remote Python interpreter. Ansible 2.17 raised the minimum
> remote Python requirement, which is not met by the Python version shipped with
> R81.20 and earlier. You will see Python-related SSH connection failures if the
> versions are mismatched.

## Installation

### Using requirements.yml (recommended)

Add to your `requirements.yml`:

```yaml
collections:
  - name: https://github.com/Webfargo/ansible-collection-check_point.git
    type: git
    version: main
```

Then install:

```bash
ansible-galaxy collection install -r requirements.yml
```

### Direct install

```bash
ansible-galaxy collection install git+https://github.com/Webfargo/ansible-collection-check_point.git
```

## Modules

### `gather_facts`

Gathers Check Point-specific system facts from Gaia OS hosts.  This module
collects the following facts:

- Check Point version (R81.20, R82, R82.10, etc.)
- Installed hotfix versions (for all installed products)
- Host type (gateway/management/standalone)
- OS code name and build number
- Deployment Agent build number
- SIC certificate info
- Hardware platform
- VSX status
- Cluster/HA status
- Check Point SNMP daemon status
- Firewall policy status (if gateway)

```yaml
- name: Gather all Check Point facts - ansible_facts
  webfargo.check_point.gather_facts:

- name: Show installed Jumbo HFA version
  ansible.builtin.debug:
    msg: >-
      {{ ansible_facts.check_point.host_type.description }},
      JHF Take {{ ansible_facts.check_point.hotfixes.FW1.jhf }}

- name: Gather all Check Point facts - registered variable
  webfargo.check_point.gather_facts:
  register: chkp_facts

- name: Installed Jumbo HFA from registered facts
  ansible.builtin.debug:
    msg: >-
      {{ chkp_facts.host_type.description }},
      JHF Take {{ chkp_facts.facts.hotfixes.FW1.jhf }}
```

Supports selective collection via `gather_subset` and automatically injects facts into
`ansible_facts.check_point` for downstream use.

### `da_status`

Read-only module for Deployment Agent status, build number, and pending reboot state.

```yaml
- webfargo.check_point.da_status:
  register: da

- debug:
    msg: "DA build {{ da.build_number }}, ready: {{ da.ready }}"
```

Includes `wait_for_ready` option to poll until the agent is fully idle
before starting operations.  When a reboot is pending, returns
`pending_reboot_message` and `pending_reboot_package` with details.

### `da_package_info`

Query available and installed packages from the Deployment Agent repository.

```yaml
# Find the Recommended Jumbo HFA
- webfargo.check_point.da_package_info:
    jumbo: recommended
    refresh: true
  register: jumbo

- debug:
    msg: "Recommended: {{ jumbo.package.filename }}"
  when: jumbo.found

# Find the Latest Jumbo HFA — may not always exist
- webfargo.check_point.da_package_info:
    jumbo: latest
    refresh: true
  register: jumbo_beta

# Filter by package category
- webfargo.check_point.da_package_info:
    category: major
  register: upgrades

# List all installed packages
- webfargo.check_point.da_package_info:
    status: installed
  register: installed

# Query a specific package by name
- webfargo.check_point.da_package_info:
    name: "Check_Point_R82_jumbo_hf_main_Bundle_T60_FULL.tgz"
  register: pkg
```

The `jumbo`, `category`, `status`, and `name` parameters are mutually
exclusive.  The `jumbo` parameter provides smart selection of Jumbo HFA
packages by release train; see **Jumbo HFA Release Trains** below.

### `da_package`

State-driven package management — the primary workhorse module.  Handles
download, import, verify, install, upgrade, and delete operations with
built-in async polling.

```yaml
# Install Recommended Jumbo HFA (auto-detect, download, verify, install)
- webfargo.check_point.da_package:
    state: installed
    refresh: true
    reboot_delay: 60
    timeout: 1800

# Download a specific package
- webfargo.check_point.da_package:
    name: "Check_Point_R82_jumbo_hf_main_Bundle_T60_FULL.tgz"
    state: downloaded

# Import and install a private hotfix
- webfargo.check_point.da_package:
    name: "custom_hotfix.tgz"
    state: imported
    location: /var/tmp

- webfargo.check_point.da_package:
    name: "custom_hotfix.tgz"
    state: installed
    reboot_delay: 60
    timeout: 1200

# Version upgrade (handles reboot-during-progress quirk)
- webfargo.check_point.da_package:
    name: "Check_Point_R82_T777_Gaia_Install_and_Upgrade.tgz"
    state: upgraded
    timeout: 3600
```

Supported states: `downloaded`, `private_download`, `imported`, `verified`,
`installed`, `upgraded`, `absent`.

#### Private Package Download

The `private_download` state uses `da_cli add_private_package` to download
unpublished packages from Check Point's online repository.  These are
packages that don't appear in public package listings but are known by name
— typically hotfixes or patches obtained through a TAC case.

```yaml
- webfargo.check_point.da_package:
    name: "Check_Point_R82_PRIVATE_HF_12345.tgz"
    state: private_download

- webfargo.check_point.da_package:
    name: "Check_Point_R82_PRIVATE_HF_12345.tgz"
    state: installed
    reboot_delay: 60
```

The package name must be known in advance.  This is distinct from
`downloaded` which pulls from the public repository.

#### Typical Jumbo HFA Workflow

A single `state: installed` task handles verify and install, but the package
must already be in the local repository.  For a complete workflow that
ensures the package is available:

```yaml
- name: Find Recommended Jumbo HFA
  webfargo.check_point.da_package_info:
    jumbo: recommended
    refresh: true
  register: jumbo

- name: Fail if no Jumbo found
  fail:
    msg: "No Recommended Jumbo HFA available"
  when: not jumbo.found

- name: Download if needed
  webfargo.check_point.da_package:
    name: "{{ jumbo.package.filename }}"
    state: downloaded

- name: Install
  webfargo.check_point.da_package:
    name: "{{ jumbo.package.filename }}"
    state: installed
    reboot_delay: 60
    timeout: 1800
```

Each task is idempotent — `downloaded` is a no-op if the package is already
in the local repository, and `installed` is a no-op if already installed.

### `da_command`

Escape hatch for arbitrary `da_cli` subcommands not covered by the other
modules.

```yaml
- webfargo.check_point.da_command:
    command: "collect_logs destination=/var/tmp/da_logs"
    wait: true
    timeout: 300
```

## Module Utils

### `da_cli.py`

Shared library providing the `DaCliClient` class used by all `da_*` modules. 
Handles JSON parsing, key normalization, embedded message extraction, async
action polling, and the various `da_cli` behavioral quirks:

- Progress 100 does not mean done — always waits for Status to change
- Progress can be an empty string (e.g. during delete operations)
- `check_for_updates` returns Action ID -1 but is actually async
- Upgrade operations reboot mid-progress and resume with the same Action ID
- `get_version` is not useful; build number comes from `da_status` or `dbget`
- Verify "failure" with message-code DEPENDENCY means already installed

## Jumbo HFA Release Trains

Check Point publishes Jumbo HFA updates on two release trains:

**Recommended** — the stable, production-ready release.  Check Point
internally marks this with `tag.importance == "latest"` in the package
metadata (confusing, but that is their convention).  Select with `jumbo:
recommended`.

**Latest** — effectively a public beta.  The next package that may
eventually become the Recommended release.  These packages have 
`category == "jumbo"` but no `tag.importance` set.  Not always available —
there may be no Latest package between Recommended releases.  Select with
`jumbo: latest`.

Package categories returned by the Deployment Agent:

| Category | Description | User-initiated |
|----------|-------------|---------------|
| `jumbo` | Jumbo Hotfix Accumulator packages | Yes |
| `major` | Major version upgrade packages (e.g. R81.20 → R82) | Yes |
| `misc` | Custom hotfixes, auto-installed tools, database migrations | Rarely |

The `isHfa` field on package objects is unreliable (can be `false` on actual Jumbo HFAs). The modules use `category` and `tag.importance` for identification instead.

## Notes

### Check Point Environment

Commands that interact with Check Point binaries (`cpprod_util`, `fw stat`,
`cpinfo`, etc.) require the Check Point shell environment.  The
`gather_facts` module handles this by sourcing `/etc/profile.d/CP.sh` before
command execution (configurable via `cp_env_script`).  The `da_cli` binary
does not require this.

### Python Interpreter on Check Point Hosts

Check Point hosts typically have `/usr/bin/python3` symlinked to the Check
Point Python installation.  If this is not the case, set the interpreter in
inventory or use a pre_task:

```yaml
# In group_vars/firewalls.yml
ansible_python_interpreter: /opt/CPsuite-R82/fw1/Python/bin/python3

# Or dynamically with block/rescue
- block:
    - webfargo.check_point.gather_facts:
  rescue:
    - set_fact:
        ansible_python_interpreter: "/opt/CPsuite-{{ chkp_ver | upper }}/fw1/Python/bin/python3"
    - webfargo.check_point.gather_facts:
```

### DA Version Compatibility

Not all hosts run the same DA build.  Certain packages require a minimum DA
build to import or install.  The DA does not auto-update itself.  There is
no reliable programmatic compatibility check; the modules surface whatever
error `da_cli` returns.

## License

GPL-3.0-or-later
