# ckp_gather_facts → `webfargo.check_point.ckp_facts` Module Design

## Current State: The Role

The `ckp_gather_facts` role runs a series of Check Point CLI commands over
SSH, parses their output using `ansible.utils.cli_parse` templates (regex-based),
and sets Ansible facts for downstream playbook use. It lives in its own Galaxy
role repo at `/opt/ansible_shared/roles/ckp_gather_facts/`.

### What the Role Collects

| Fact Area | Command(s) | Parsing Method |
|-----------|-----------|----------------|
| Standard Ansible facts | `gather_facts` module (with Python interpreter fallback) | Built-in |
| SIC certificate info | `ckp_regedit -p Software/CheckPoint/SIC` | cli_parse regex (3 variants) |
| Host type (gateway/mgmt/both) | `cpprod_util FwIsFirewallModule`, `cpprod_util FwIsFirewallMgmt` | stdout == "1" or "0" |
| Firewall policy (gw only) | `fw stat` | cli_parse regex |
| Installed hotfix/JHF versions | `cpinfo -y all` | cli_parse regex (multi-line, stateful) |
| VSX gateway status | `cpprod_util FwIsVSX` | stdout bool |
| Cluster/HA status | `cpprod_util FwIsHighAvail` | stdout bool |
| Hardware platform | `clish -c 'show asset system'` | string search (PowerEdge/ProLiant) |

### Pain Points in the Role

- **Python interpreter dance:** The role has a block/rescue/always to handle
  missing Python on Check Point hosts, with a fallback path derived from
  `ckp_ver` (`/opt/CPsuite-R81.20/fw1/Python/bin/python3`). After
  `gather_facts` succeeds, it resets the interpreter to the discovered
  `ansible_facts.python.executable`.
- **FQDN preservation:** `gather_facts` can clobber the FQDN; the role
  saves it to `host_fqdn` before and restores `ansible_fqdn` after.
- **cli_parse templates:** Three separate regex variants for SIC parsing
  depending on host type (gateway, management, standalone). Each handles
  different casing (`CN` vs `cn`, `O` vs `o`) and presence/absence of
  fields like `ICAip` and `ICAState`. The standalone variant appends a
  trailing dot to `ica_dn` to normalize it.
- **cpinfo parsing is stateful:** The `[PRODUCT]` header lines set context
  for subsequent hotfix lines — uses `shared: true` in cli_parse to carry
  `product` across template entries. Three separate regex entries handle
  JUMBO_HF_MAIN (take), JHF_COMP (take), and other hotfixes (name only).
- **Multiple shell tasks with `. /etc/profile.d/CP.sh`** needed to get
  Check Point commands in PATH before running `cpprod_util`, `fw stat`, etc.
- **Hardware detection** uses `clish -c 'show asset system' | grep -v CLINFR`
  with multiple `when:` conditions on string search results.
- **Boolean fact conversion:** `cpprod_util` returns `"1"` or `"0"` as
  stdout; the role uses `|join('') |bool` to convert, which works but
  is fragile with whitespace.

---

## Proposed Module: `webfargo.check_point.ckp_facts`

A single module that collects all Check Point-specific facts in one call,
returning a structured dict. The module runs on the target host and uses
`module.run_command()` for all CLI interactions.

### Module Interface

```yaml
- name: Gather Check Point facts
  webfargo.check_point.ckp_facts:
    gather_subset:
      - all            # default: collect everything
    # Or selectively:
    # gather_subset:
    #   - sic
    #   - host_type
    #   - policy
    #   - hotfixes
    #   - vsx
    #   - cluster
    #   - hardware
  register: ckp

# Access facts:
#   ckp.facts.sic.name
#   ckp.facts.host_type.is_gateway
#   ckp.facts.host_type.is_management
#   ckp.facts.policy.package
#   ckp.facts.hotfixes.FW1.jhf
#   ckp.facts.vsx
#   ckp.facts.cluster
#   ckp.facts.hardware.platform
```

### Return Structure

```yaml
facts:
  sic:
    ica_dn: "O=cpmgmt01.webfargo.com.dhbubh"
    name: "CN=cpgw,O=cpmgmt01.webfargo.com.dhbubh"
    cn: "cpgw"
    o: "cpmgmt01.webfargo.com.dhbubh"
    cert_path: "/opt/CPshrd-R80.40/conf/sic_cert.p12"
    ica_ip: "10.27.0.250"    # only present on gateways
    # On management/standalone hosts, ica_ip is absent because
    # the host IS the management server. Playbooks can use
    # ansible_host as the ICA IP when ica_ip is missing.

  host_type:
    is_gateway: true
    is_management: false
    is_standalone: false     # derived: both gateway AND management
    description: "gateway"   # "gateway", "management", "standalone"

  policy:                    # only populated if is_gateway
    gw_host: "localhost"
    policy_package: "Standard"
    policy_date: "18Oct2023 11:24:27"

  hotfixes:                  # keyed by product name (spaces → underscores)
    FW1:
      name: "FW1"
      jhf: "83"
      hotfixes:
        - "HOTFIX_R80_40_JUMBO_HF_MAIN"
        - "HOTFIX_R80_40_JHF_COMP"
        - "HOTFIX_PUBLIC_CLOUD_CA_BUNDLE_AUTOUPDATE"
    SVN_Foundation:
      name: "SVN Foundation"
      jhf: "83"
      hotfixes:
        - "HOTFIX_R80_40_JUMBO_HF_MAIN"

  vsx: true                  # or false
  cluster: true              # or false

  hardware:
    platform: "dell"         # "dell", "hp", "checkpoint_appliance", "virtual", "unknown"
    model: "PowerEdge R640"  # raw model string from clish output
```

---

## Module Implementation

```python
# plugins/modules/ckp_facts.py
```

---

## Playbook Comparison

### Before: Role Approach

```yaml
- hosts: firewalls
  gather_facts: false

  roles:
    - ckp_gather_facts

  tasks:
    - debug:
        msg: "JHF: {{ ckp_cpinfo.FW1.jhf }}"
```

The role internally runs ~15 tasks:
1. Save `ansible_fqdn` to `host_fqdn`
2. `gather_facts` in a block/rescue/always with Python interpreter fallback
3. Restore `ansible_fqdn` from saved value
4. `ckp_regedit -p Software/CheckPoint/SIC` → cli_parse (3 regex variants)
5. `cpprod_util FwIsFirewallModule` → shell + register + bool conversion
6. `cpprod_util FwIsFirewallMgmt` → shell + register + bool conversion
7. `fw stat` → cli_parse (conditional on gateway)
8. `cpinfo -y all` → cli_parse (stateful template with `shared: true`)
9. `cpprod_util FwIsVSX` → shell + register + bool conversion
10. `cpprod_util FwIsHighAvail` → shell + register + bool conversion
11. `clish -c 'show asset system'` → shell + multiple `when:` conditionals

Each uses `. /etc/profile.d/CP.sh &&` prefix, `register:`, `set_fact:`,
and cli_parse templates in separate YAML files.

### After: Module Approach

```yaml
- hosts: firewalls
  gather_facts: false

  tasks:
    - name: Gather Check Point facts
      webfargo.check_point.ckp_facts:
      register: ckp

    - debug:
        msg: "JHF: {{ ckp.facts.hotfixes.FW1.jhf }}"

    # Or via ansible_facts (set_ansible_facts: true is default)
    - debug:
        msg: "Policy: {{ ansible_facts.ckp.policy.policy_package }}"
      when: ansible_facts.ckp.host_type.is_gateway
```

### Selective Collection

```yaml
- name: Just check host type and hotfixes
  webfargo.check_point.ckp_facts:
    gather_subset:
      - host_type
      - hotfixes
  register: ckp
```

---

## What About gather_facts / Python Interpreter?

The role currently wraps Ansible's `gather_facts` with a block/rescue to
handle the Python interpreter issue on Check Point hosts. This is **separate
from the ckp_facts module** and should remain a playbook-level concern:

```yaml
- hosts: firewalls
  gather_facts: false

  pre_tasks:
    # Handle Check Point's Python interpreter location
    - name: Gather standard facts
      block:
        - gather_facts:
      rescue:
        - set_fact:
            ansible_python_interpreter: >-
              /opt/CPsuite-{{ ckp_ver | upper }}/fw1/Python/bin/python3
        - gather_facts:
      always:
        - set_fact:
            ansible_python_interpreter: "{{ ansible_facts.python.executable }}"
            ansible_fqdn: "{{ saved_fqdn }}"

  tasks:
    - name: Gather Check Point facts
      webfargo.check_point.ckp_facts:
      register: ckp
```

The ckp_facts module itself doesn't need the Python interpreter dance
because `module.run_command()` executes commands via the shell — it
doesn't need Python on the remote host for the Check Point CLI commands.
However, the module **does** need Python to run (as all Ansible modules do),
so the interpreter must be set correctly before calling it.

Alternatively, you could set `ansible_python_interpreter` in inventory or
group_vars for Check Point hosts, avoiding the block/rescue entirely.

---

## Key Improvements Over the Role

1. **SIC parsing:** Three cli_parse regex variants (gateway/mgmt/standalone)
   collapsed into one Python method with flexible regex that handles all cases
   including inconsistent CN/cn casing.

2. **cpinfo parsing:** The stateful `[PRODUCT]` → hotfix line parsing is
   natural in Python (just track `current_product`) but was awkward in
   cli_parse with `shared: true`.

3. **Single module call:** One task instead of 6+ shell tasks + cli_parse +
   set_fact chains. Faster execution (fewer SSH round-trips if using
   `raw`/`shell`).

4. **Structured return:** All facts in one dict vs. scattered `set_fact`
   variables. Easier to reference, pass around, and conditionally collect.

5. **gather_subset:** Collect only what you need instead of everything every time.

6. **No cli_parse dependency:** Eliminates the `ansible.utils` / `ansible.netcommon`
   collection dependency for parsing.

7. **Derived facts:** `is_standalone` (gateway AND management) computed
   automatically. Host type `description` string for easy display.

---

## Migration Path

1. Add `ckp_facts.py` to `webfargo.check_point` collection alongside the
   da_cli modules.
2. Test on a representative set of hosts (gateway, management, standalone,
   VSX, cluster, various hardware).
3. Run old role and new module side by side, compare output.
4. Update playbooks to use `webfargo.check_point.ckp_facts`.
5. Archive the role repo (tag it, keep the `git filter-repo` history).
