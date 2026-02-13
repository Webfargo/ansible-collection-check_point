#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Webfargo Data Security, Inc.
# GNU General Public License v3.0+

from ansible.module_utils.basic import AnsibleModule
import re

DOCUMENTATION = r"""
---
module: gather_facts
short_description: Gather Check Point Gaia OS specific facts
description:
  - Collects Check Point-specific system information from Gaia OS hosts
    including SIC configuration, host type (gateway/management/standalone),
    installed firewall policy, hotfix versions, VSX status, cluster status,
    and hardware platform.
  - All facts are returned in a structured dict under C(facts) and
    optionally injected into C(ansible_facts) for downstream use.
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
      - If true, inject collected facts into C(ansible_facts.check_point) so
        they can be referenced as C(ansible_facts.check_point.sic.name) etc.
    type: bool
    default: true
  cp_env_script:
    description:
      - Path to the Check Point environment script that sets up PATH
        and other environment variables.
    type: str
    default: /etc/profile.d/CP.sh
author:
  - Duane Toler <dtoler@webfargo.com>
"""

EXAMPLES = r"""
- name: Gather all Check Point facts
  webfargo.check_point.gather_facts:
  register: chkp_facts

- name: Show host type
  debug:
    msg: "This host is a {{ chkp_facts.host_type.description }}"

- name: Show SIC info
  debug:
    msg: "SIC name: {{ chkp_facts.sic.name }}"

- name: Only gather hotfix and host type info
  webfargo.check_point.gather_facts:
    gather_subset:
      - hotfixes
      - host_type
  register: chkp_facts

- name: Show Jumbo HFA take for FW1
  debug:
    msg: "JHF Take: {{ chkp_facts.hotfixes.FW1.jhf }}"
  when: "'FW1' in chkp_facts.hotfixes"

- name: Conditional on gateway
  block:
    - name: Do gateway-specific things
      debug:
        msg: "Policy: {{ ansible_facts.check_point.policy.policy_package }}"
  when: ansible_facts.check_point.host_type.is_gateway
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
            use_cp_env: If True, source the Check Point environment script first
                so that Check Point binaries are in PATH.

        Returns:
            (rc, stdout, stderr) tuple
        """
        if use_cp_env:
            full_cmd = f". {self.cp_env}; {command}"
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
          localhost Standard         21Dec2112 11:24:27 :  [>eth0] [<eth0]

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
            platform = "check_point_appliance"
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
        result["ansible_facts"] = {"check_point": facts}

    module.exit_json(**result)


if __name__ == "__main__":
    main()
