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

DOCUMENTATION = r"""
---
module: ckp_facts
short_description: Gather Check Point Gaia OS specific facts
description:
  - Collects Check Point-specific system information from Gaia OS hosts
    including SIC configuration, host type (gateway/management/standalone),
    installed firewall policy, hotfix versions, VSX status, cluster status,
    and hardware platform.
  - All facts are returned in a structured dict under C(facts) and
    optionally injected into C(ansible_facts) for downstream use.
  - This module replaces the ckp_gather_facts role with proper Python
    parsing instead of cli_parse regex templates.
options:
  gather_subset:
    description:
      - List of fact subsets to collect.
      - C(all) collects everything (default).
      - Individual subsets can be specified to limit collection.
    type: list
    elements: str
    choices: [all, sic, host_type, policy, hotfixes, vsx, cluster, hardware]
    default: [all]
  set_ansible_facts:
    description:
      - If true, inject collected facts into C(ansible_facts.ckp) so
        they can be referenced as C(ansible_facts.ckp.sic.name) etc.
    type: bool
    default: true
  cp_env_script:
    description:
      - Path to the Check Point environment script that sets up PATH
        and other environment variables.
    type: str
    default: /etc/profile.d/CP.sh
author:
  - Palpatine
"""

EXAMPLES = r"""
- name: Gather all Check Point facts
  webfargo.check_point.ckp_facts:
  register: ckp

- name: Show host type
  debug:
    msg: "This host is a {{ ckp.facts.host_type.description }}"

- name: Show SIC info
  debug:
    msg: "SIC name: {{ ckp.facts.sic.name }}"

- name: Only gather hotfix and host type info
  webfargo.check_point.ckp_facts:
    gather_subset:
      - hotfixes
      - host_type
  register: ckp

- name: Show Jumbo HFA take for FW1
  debug:
    msg: "JHF Take: {{ ckp.facts.hotfixes.FW1.jhf }}"
  when: "'FW1' in ckp.facts.hotfixes"

- name: Conditional on gateway
  block:
    - name: Do gateway-specific things
      debug:
        msg: "Policy: {{ ansible_facts.ckp.policy.policy_package }}"
  when: ansible_facts.ckp.host_type.is_gateway
"""

RETURN = r"""
facts:
  description: Collected Check Point facts
  returned: always
  type: dict
  contains:
    sic:
      description: SIC certificate and identity information
      type: dict
    host_type:
      description: Gateway/management/standalone classification
      type: dict
    policy:
      description: Installed firewall policy (gateway only)
      type: dict
    hotfixes:
      description: Installed hotfixes keyed by product name
      type: dict
    vsx:
      description: Whether host is a VSX gateway
      type: bool
    cluster:
      description: Whether host is a cluster (HA) member
      type: bool
    hardware:
      description: Hardware platform information
      type: dict
"""

import re
from ansible.module_utils.basic import AnsibleModule


class CkpFactsCollector:
    """Collect Check Point-specific facts from a Gaia OS host."""

    def __init__(self, module):
        self.module = module
        self.cp_env = module.params["cp_env_script"]

    def _run(self, command, use_cp_env=True):
        """
        Run a command on the host.

        Args:
            command: Command string to execute
            use_cp_env: If True, source the CP environment script first
                so that Check Point binaries are in PATH.

        Returns:
            (rc, stdout, stderr) tuple
        """
        if use_cp_env:
            full_cmd = f". {self.cp_env} && {command}"
        else:
            full_cmd = command

        return self.module.run_command(full_cmd, use_unsafe_shell=True)

    def _run_cpprod_util(self, check):
        """
        Run a cpprod_util boolean check.

        Args:
            check: The check name (e.g. "FwIsFirewallModule")

        Returns:
            True if output is "1", False otherwise
        """
        rc, stdout, stderr = self._run(f"cpprod_util {check}")
        return stdout.strip() == "1"

    # ----- SIC Facts -----

    def gather_sic(self):
        """
        Parse SIC information from ckp_regedit.

        Handles three host variants with real-world examples:

        1. Gateway only:
           'ICAdn=[s]O=cpmgmt01.webfargo.com.dhbubh
            MySICname=[s]CN=cpgw,O=cpmgmt01.webfargo.com.dhbubh
            CertPath=[s]/opt/CPshrd-R80.40/conf/sic_cert.p12
            ICAip=[s]10.27.0.250'
           → Has ICAip (management server IP), CN and O are distinct

        2. Standalone (integrated gw+mgmt):
           'ICAState=[n]3 ICAdn=[s]o=nutmeg..jzz6nv
            MySICname=[s]cn=cp_mgmt,o=nutmeg..jzz6nv
            CertPath=[s]/opt/CPshrd-R81.20/conf/sic_cert.p12'
           → No ICAip (it IS the management), cn is always "cp_mgmt",
             ICAdn may be truncated (no dots in org part)

        3. Management only:
           'ICAdn=[s]o=mercury.mrnc.org.o7shmo
            MySICname=[s]cn=cp_mgmt,o=mercury.mrnc.org.o7shmo
            CertPath=[s]/opt/CPshrd-R80.40/conf/sic_cert.p12'
           → No ICAip (it IS the management), cn is always "cp_mgmt",
             ICAdn has dots in org

        Note: The casing is inconsistent (CN vs cn, O vs o) across hosts.
        The entire output is on a single line wrapped in braces.
        """
        rc, stdout, stderr = self._run(
            "ckp_regedit -p Software/CheckPoint/SIC"
        )

        if rc != 0 or not stdout.strip():
            return {"error": "Could not read SIC registry"}

        line = stdout.strip()
        result = {}

        # Extract ICAdn — case-insensitive O= prefix
        m = re.search(r'ICAdn=\[s\][Oo]=(\S+)', line)
        if m:
            result["ica_dn"] = f"O={m.group(1)}"

        # Extract MySICname — handles both:
        #   CN=cpgw,O=cpmgmt01.webfargo.com.dhbubh  (gateway)
        #   cn=cp_mgmt,o=nutmeg..jzz6nv             (mgmt/standalone)
        m = re.search(
            r'MySICname=\[s\](?:[Cc][Nn])=([^,\s]+)'
            r'(?:,(?:[Oo])=(\S+))?',
            line,
        )
        if m:
            result["cn"] = m.group(1)
            if m.group(2):
                result["o"] = m.group(2)
                result["name"] = f"CN={m.group(1)},O={m.group(2)}"
            else:
                # Management server SIC name without O= component
                result["name"] = f"CN={m.group(1)}"

        # Extract CertPath
        m = re.search(r'CertPath=\[s\](\S+)', line)
        if m:
            result["cert_path"] = m.group(1)

        # Extract ICAip — only present on gateways (not mgmt/standalone)
        m = re.search(r'ICAip=\[s\]([0-9.]+)', line)
        if m:
            result["ica_ip"] = m.group(1)
        # If no ICAip, this host IS the management server.
        # The caller can set ica_ip to ansible_host if needed.

        return result

    # ----- Host Type Facts -----

    def gather_host_type(self):
        """Determine if host is gateway, management, or standalone."""
        is_gw = self._run_cpprod_util("FwIsFirewallModule")
        is_mgmt = self._run_cpprod_util("FwIsFirewallMgmt")

        is_standalone = is_gw and is_mgmt

        if is_standalone:
            description = "standalone"
        elif is_gw:
            description = "gateway"
        elif is_mgmt:
            description = "management"
        else:
            description = "unknown"

        return {
            "is_gateway": is_gw,
            "is_management": is_mgmt,
            "is_standalone": is_standalone,
            "description": description,
        }

    # ----- Policy Facts -----

    def gather_policy(self, is_gateway=True):
        """
        Get installed firewall policy from 'fw stat'.

        Only meaningful on gateway hosts.

        Example output:
          localhost Standard         18Oct2023 11:24:27 :  [>eth0] [<eth0]

        The cli_parse template extracted: host, name (policy package), date
        """
        if not is_gateway:
            return {}

        rc, stdout, stderr = self._run("fw stat")
        if rc != 0 or not stdout.strip():
            return {"error": "fw stat failed or no policy installed"}

        # Match: host  policyname  DDMonYYYY HH:MM:SS :
        m = re.search(
            r'(\S+)\s+(\S+)\s+(\d+\w+\d+\s+\d+:\d+:\d+)\s+:',
            stdout,
        )

        if m:
            return {
                "gw_host": m.group(1),
                "policy_package": m.group(2),
                "policy_date": m.group(3),
            }

        return {"raw": stdout.strip()}

    # ----- Hotfix / JHF Facts -----

    def gather_hotfixes(self):
        """
        Parse cpinfo -y all output for installed hotfixes and JHF takes.

        The output is stateful — product headers like [FW1] set context
        for subsequent hotfix lines. This is much cleaner in Python than
        in cli_parse regex templates with shared state.

        Example output:
            [FW1]
              HOTFIX_R80_40_JUMBO_HF_MAIN  Take:  83
              HOTFIX_R80_40_JHF_COMP       Take:  198
              HOTFIX_PUBLIC_CLOUD_CA_BUNDLE_AUTOUPDATE
            [SVN Foundation]
              HOTFIX_R80_40_JUMBO_HF_MAIN  Take:  83
        """
        rc, stdout, stderr = self._run("cpinfo -y all")
        if rc != 0:
            return {"error": "cpinfo failed"}

        result = {}
        current_product = None

        for line in stdout.splitlines():
            line = line.rstrip()

            # Product header: [FW1], [SVN Foundation], etc.
            m = re.match(r'^\[(.+)\]$', line)
            if m:
                product_name = m.group(1)
                # Key uses underscores for easier Ansible access
                product_key = product_name.replace(" ", "_")
                current_product = product_key
                result[product_key] = {
                    "name": product_name,
                    "jhf": None,
                    "hotfixes": [],
                }
                continue

            if current_product is None:
                continue

            stripped = line.strip()
            if not stripped:
                continue

            # Jumbo HF main take: "HOTFIX_R80_40_JUMBO_HF_MAIN  Take:  83"
            m = re.match(r'(HOTFIX_\S*JUMBO_HF_MAIN)\s+Take:\s+(\d+)', stripped)
            if m:
                result[current_product]["jhf"] = m.group(2)
                result[current_product]["hotfixes"].append(m.group(1))
                continue

            # JHF component take: "HOTFIX_R80_40_JHF_COMP  Take:  198"
            # This is an alternative JHF version indicator; use it if
            # JUMBO_HF_MAIN wasn't found
            m = re.match(r'(HOTFIX_\S*JHF_COMP)\s+Take:\s+(\d+)', stripped)
            if m:
                if result[current_product]["jhf"] is None:
                    result[current_product]["jhf"] = m.group(2)
                result[current_product]["hotfixes"].append(m.group(1))
                continue

            # Other hotfix line (no Take): "HOTFIX_PUBLIC_CLOUD_CA_..."
            m = re.match(r'(HOTFIX_\S+)', stripped)
            if m:
                result[current_product]["hotfixes"].append(m.group(1))
                continue

        return result

    # ----- VSX Facts -----

    def gather_vsx(self):
        """Check if host is a VSX gateway."""
        return self._run_cpprod_util("FwIsVSX")

    # ----- Cluster Facts -----

    def gather_cluster(self):
        """Check if host is a cluster (HA) member."""
        return self._run_cpprod_util("FwIsHighAvail")

    # ----- Hardware Facts -----

    def gather_hardware(self):
        """
        Determine hardware platform from clish output.

        Known platforms:
        - Dell PowerEdge
        - HP ProLiant
        - Check Point appliance (various models)
        - Virtual (VMware, KVM, Hyper-V)
        """
        rc, stdout, stderr = self._run(
            "clish -c 'show asset system'",
        )

        if rc != 0:
            return {"platform": "unknown", "model": "unknown"}

        output = stdout.strip()

        # Determine platform
        if "PowerEdge" in output:
            platform = "dell"
        elif "ProLiant" in output:
            platform = "hp"
        elif "Check Point" in output:
            platform = "checkpoint_appliance"
        elif any(v in output.lower() for v in ("vmware", "virtual", "kvm", "hyper-v")):
            platform = "virtual"
        else:
            platform = "unknown"

        # Extract model string (best effort)
        model = "unknown"
        for line in output.splitlines():
            # Look for a line containing the model info
            # clish output varies but typically has a "Product Name" or
            # similar field
            if any(k in line for k in ("PowerEdge", "ProLiant", "Check Point")):
                model = line.strip()
                break

        return {
            "platform": platform,
            "model": model,
        }


def main():
    module = AnsibleModule(
        argument_spec=dict(
            gather_subset=dict(
                type="list",
                elements="str",
                default=["all"],
            ),
            set_ansible_facts=dict(type="bool", default=True),
            cp_env_script=dict(type="str", default="/etc/profile.d/CP.sh"),
        ),
        supports_check_mode=True,
    )

    subset = module.params["gather_subset"]
    collect_all = "all" in subset

    collector = CkpFactsCollector(module)
    facts = {}

    # --- Host type is gathered first since policy depends on it ---
    if collect_all or "host_type" in subset:
        facts["host_type"] = collector.gather_host_type()

    if collect_all or "sic" in subset:
        facts["sic"] = collector.gather_sic()

    # Policy only makes sense on gateways
    is_gw = facts.get("host_type", {}).get("is_gateway", True)
    if collect_all or "policy" in subset:
        facts["policy"] = collector.gather_policy(is_gateway=is_gw)

    if collect_all or "hotfixes" in subset:
        facts["hotfixes"] = collector.gather_hotfixes()

    if collect_all or "vsx" in subset:
        facts["vsx"] = collector.gather_vsx()

    if collect_all or "cluster" in subset:
        facts["cluster"] = collector.gather_cluster()

    if collect_all or "hardware" in subset:
        facts["hardware"] = collector.gather_hardware()

    result = {
        "changed": False,
        "facts": facts,
    }

    # Optionally inject into ansible_facts
    if module.params["set_ansible_facts"]:
        result["ansible_facts"] = {"ckp": facts}

    module.exit_json(**result)


if __name__ == "__main__":
    main()
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
