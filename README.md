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
> remote Python requirement, which is not compatible with the Python version shipped with
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

Gathers Check Point-specific system facts from Gaia OS hosts. This module
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
- Cloud platform metadata (Azure, AWS, GCP, etc.)

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

- name: Check if host is an Azure VM
  ansible.builtin.debug:
    msg: "Cloud platform: {{ chkp_facts.cloud_info.platform }}"
  when: chkp_facts.cloud_info.platform is defined
```

Supports selective collection via `gather_subset` and automatically injects facts into
`ansible_facts.check_point` for downstream use.

The `cloud_info` subset reads `/etc/cloud-version.json` (with fallback to
`/etc/cloud-version`) and returns fields including `platform`, `release`, `take`,
`license`, `deployment_method`, `template_name`, `template_version`, and
`template_type`. Returns an empty dict on non-cloud hosts.

### `da_status`

Read-only module for Deployment Agent status, build number, and pending reboot state.

```yaml
- webfargo.check_point.da_status:
  register: da

- debug:
    msg: "DA build {{ da.build_number }}, ready: {{ da.ready }}"
```

Includes `wait_for_ready` option to poll until the agent is fully idle
before starting operations. When a reboot is pending, returns
`pending_reboot_message` and `pending_reboot_package` with details.

**Recommended practice:** Call `da_status` with `wait_for_ready: true` as the
first task in any package operation playbook to ensure the DA is idle before
proceeding.

```yaml
- name: Wait for DA to be ready
  webfargo.check_point.da_status:
    wait_for_ready: true
    timeout: 120
```

**Note:** `Update Status: "not allowed"` (hosts without Check Point Cloud access)
is treated as a valid ready state and does not block `wait_for_ready`.

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
exclusive. The `jumbo` parameter provides smart selection of Jumbo HFA
packages by release train; see **Jumbo HFA Release Trains** below.

The `name` query returns `fail_json` with a clear message if the package is
not found or the name is invalid (wrong extension, etc.).

**Note:** `jumbo` mode returns a single `package` dict, not a `packages` list.
Use bracket notation for hyphenated keys in Jinja2 templates:
`result['warning-install']`.

### `da_package`

State-driven package management — the primary workhorse module. Handles
download, import, verify, install, upgrade, uninstall, and delete operations
with built-in async polling.

```yaml
# Install Recommended Jumbo HFA (auto-detect, download, verify, install)
- webfargo.check_point.da_package:
    state: installed
    refresh: true
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
    timeout: 1200

# Check uninstall eligibility before removing
- webfargo.check_point.da_package:
    name: "Check_Point_R82_jumbo_hf_main_Bundle_T91_FULL.tgz"
    state: verify_uninstall
  register: verify_uninstall_result

# Uninstall a package
- webfargo.check_point.da_package:
    name: "Check_Point_R82_jumbo_hf_main_Bundle_T91_FULL.tgz"
    state: absent
    uninstall_method: completely

# Version upgrade (two-stage — see Version Upgrade section below)
- webfargo.check_point.da_package:
    name: "Check_Point_R82_T777_Gaia_Install_and_Upgrade.tgz"
    state: upgraded
    timeout: 3600
  register: upgrade_result
  ignore_errors: true
```

Supported states: `downloaded`, `private_download`, `imported`, `verified`,
`verify_uninstall`, `installed`, `upgraded`, `absent`.

#### Key Parameters

- `reboot_delay` (default 30) — delay in seconds before reboot after install,
  uninstall, or upgrade. Required to ensure the module receives a clean result
  before the host reboots.
- `verify_before_install` (default true) — automatically run verify before
  install or upgrade.
- `verify_before_uninstall` (default true) — automatically run verify_uninstall
  before uninstalling. Catches dependency blocks (e.g. a newer take is installed
  on top and must be removed first).
- `poll_interval` (default 5) — seconds between status polls. 5 seconds is
  required to reliably detect the reboot signal window during upgrades.
- `timeout` (default 900) — maximum seconds to wait for an action to complete.

#### Reboot Handling

Operations that trigger a reboot (install, uninstall, upgrade) require
additional playbook tasks to handle the host going down and coming back.
Do NOT use `ansible.builtin.reboot` — the DA triggers the reboot itself.

For install and uninstall, the module detects the reboot signal and returns
before the host goes down. Add a `wait_for` + `wait_for_connection` block
after the task:

```yaml
- name: Install package
  webfargo.check_point.da_package:
    name: "{{ package }}"
    state: installed
    timeout: 1800
  register: install_result

- name: Wait for host to come back
  when: install_result.changed
  block:
    - name: Wait for SSH to go down
      ansible.builtin.wait_for:
        host: "{{ inventory_hostname }}"
        port: 22
        state: stopped
        delay: 10
        timeout: 120
      delegate_to: localhost

    - name: Wait for SSH to come back
      ansible.builtin.wait_for_connection:
        connect_timeout: 3
        delay: 30
        sleep: 5
        timeout: 600
  rescue:
    - name: Wait for SSH to come back (rescue)
      ansible.builtin.wait_for_connection:
        connect_timeout: 3
        delay: 10
        sleep: 5
        timeout: 600
```

**Azure VMs** reboot significantly faster than physical hardware. Use
`ckp_facts.cloud_info.platform` from the `gather_facts` module to apply a
shorter delay:

```yaml
    delay: "{{ 15 if ckp_facts.cloud_info.platform | default('') == 'azure' else 30 }}"
```

#### Version Upgrade — Two-Stage Operations

Upgrade operations (Blink images and clean install packages) use a two-stage
process that reboots between stages. The module cannot survive the reboot and
returns `status: reboot_pending` when stage 1 completes. Stage 2 runs after
reboot and must be monitored separately.

Use `ignore_errors: true` on the upgrade task to handle platforms where the
reboot signal may not be observed before SSH drops:

```yaml
- name: Execute upgrade
  webfargo.check_point.da_package:
    name: "{{ upgrade_package }}"
    state: upgraded
    verify_before_install: false
    timeout: 3600
  register: upgrade_result
  ignore_errors: true

- name: Wait for reboot and stage 2
  when: >
    upgrade_result.status | default('') == "reboot_pending" or
    upgrade_result.failed | default(false)
  block:
    - name: Wait for SSH to come back
      ansible.builtin.wait_for_connection:
        connect_timeout: 3
        delay: 30
        sleep: 15
        timeout: 600

    - name: Wait for stage 2 completion
      webfargo.check_point.da_status:
        wait_for_ready: true
        timeout: 1800
  rescue:
    - name: Wait for SSH to come back (rescue)
      ansible.builtin.wait_for_connection:
        connect_timeout: 3
        delay: 60
        sleep: 15
        timeout: 600
```

#### Private Package Download

The `private_download` state uses `da_cli add_private_package` to download
unpublished packages from Check Point's online repository. These are
packages that don't appear in public package listings but are known by name
— typically hotfixes or patches obtained through a TAC case.

```yaml
- webfargo.check_point.da_package:
    name: "Check_Point_R82_PRIVATE_HF_12345.tgz"
    state: private_download

- webfargo.check_point.da_package:
    name: "Check_Point_R82_PRIVATE_HF_12345.tgz"
    state: installed
```

The package name must be known in advance. This is distinct from
`downloaded` which pulls from the public repository.

#### Typical Jumbo HFA Workflow

A single `state: installed` task handles verify and install, but the package
must already be in the local repository. For a complete workflow that
ensures the package is available:

```yaml
- name: Wait for DA to be ready
  webfargo.check_point.da_status:
    wait_for_ready: true
    timeout: 120

- name: Find Recommended Jumbo HFA
  webfargo.check_point.da_package_info:
    jumbo: recommended
    refresh: true
  register: jumbo

- name: Fail if no Jumbo found
  ansible.builtin.fail:
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
    timeout: 1800
  register: install_result

- name: Wait for host to come back after reboot
  when: install_result.changed
  block:
    - name: Wait for SSH to go down
      ansible.builtin.wait_for:
        host: "{{ inventory_hostname }}"
        port: 22
        state: stopped
        delay: 10
        timeout: 120
      delegate_to: localhost

    - name: Wait for SSH to come back
      ansible.builtin.wait_for_connection:
        connect_timeout: 3
        delay: 30
        sleep: 5
        timeout: 600
  rescue:
    - name: Wait for SSH to come back (rescue)
      ansible.builtin.wait_for_connection:
        connect_timeout: 3
        delay: 10
        sleep: 5
        timeout: 600
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

Use the `changed` parameter to override the default changed detection
(action commands are assumed to change state):

```yaml
- webfargo.check_point.da_command:
    command: "da_status"
    wait: false
    changed: false
```

## Module Utils

### `da_cli.py`

Shared library providing the `DaCliClient` class used by all `da_*` modules.
Handles JSON parsing, key normalization, embedded message extraction, async
action polling, and the various `da_cli` behavioral quirks:

- Progress 100 does not mean done — always waits for Status to change
- Progress can be an empty string (e.g. during delete and reboot transitions)
- `check_for_updates` returns Action ID -1 but is actually async
- Install reboot signal is `"Going to reboot:"` in the Message field
- Uninstall and upgrade reboot signal is `DAService State: "down"`
- Upgrade operations use a two-stage process; module returns `reboot_pending`
  after stage 1 — playbook handles the reboot and stage 2 monitoring
- `"interrupted"` status (e.g. DA restarted mid-operation) fails fast with
  a clear error message
- `get_version` is not useful; build number comes from `da_status` or `dbget`
- Verify "failure" with message-code DEPENDENCY means already installed
- Plain text `"Error: ..."` output (rc=1) detected and surfaced cleanly

## Jumbo HFA Release Trains

Check Point publishes Jumbo HFA updates on two release trains:

**Recommended** — the stable, production-ready release. Check Point
internally marks this with `tag.importance == "latest"` in the package
metadata (confusing, but that is their convention). Select with `jumbo:
recommended`.

**Latest** — effectively a public beta. The next package that may
eventually become the Recommended release. These packages have
`category == "jumbo"` but no `tag.importance` set. Not always available —
there may be no Latest package between Recommended releases. Select with
`jumbo: latest`.

Package categories returned by the Deployment Agent:

| Category | Description | User-initiated |
|----------|-------------|---------------|
| `jumbo` | Jumbo Hotfix Accumulator packages | Yes |
| `major` | Major version upgrade packages (e.g. R81.20 → R82) | Yes |
| `misc` | Custom hotfixes, auto-installed tools, database migrations | Rarely |

The `isHfa` field on package objects is unreliable (can be `false` on actual
Jumbo HFAs). The modules use `category` and `tag.importance` for
identification instead.

## Notes

### Check Point Environment

Commands that interact with Check Point binaries (`cpprod_util`, `fw stat`,
`cpinfo`, etc.) require the Check Point shell environment. The
`gather_facts` module handles this by sourcing `/etc/profile.d/CP.sh` before
command execution (configurable via `cp_env_script`). The `da_cli` binary
does not require this.

### Python Interpreter on Check Point Hosts

Check Point hosts typically have `/usr/bin/python3` symlinked to the Check
Point Python installation. If this is not the case, set the interpreter in
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

Not all hosts run the same DA build. Certain packages require a minimum DA
build to import or install. The DA does not auto-update itself. There is
no reliable programmatic compatibility check; the modules surface whatever
error `da_cli` returns.

### Design Document

For a detailed reference on `da_cli` behavior, package state strings, reboot
signal detection, two-stage upgrade mechanics, and known quirks, see
`cpda_module_design.md` in the collection root.

## License

GPL-3.0-or-later
