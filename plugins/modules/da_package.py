#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Webfargo Data Security, Inc.
# GNU General Public License v3.0+
# plugins/modules/da_package.py

DOCUMENTATION = r"""
---
module: da_package
short_description: Manage Check Point packages via the Deployment Agent
description:
  - Download, import, verify, install, upgrade, uninstall, and delete
    packages using the Check Point Deployment Agent CLI (da_cli).
  - Action commands are polled automatically until completion.
  - If C(name) is omitted for install, verify, or download operations,
    the module auto-detects the latest Jumbo HFA from the local repository.
  - Supports check mode for all operations.
  - Operations that trigger a reboot (install, uninstall, upgrade) require
    a C(wait_for_connection) task after the module call to handle the
    host coming back online. Use C(reboot_delay) to ensure the module
    receives a clean result before the reboot fires.
options:
  name:
    description:
      - Package filename.
      - If omitted for C(install), C(verify), or C(download) operations,
        the module auto-selects the Recommended Jumbo HFA
        (tag.importance == latest).
    type: str
  state:
    description:
      - Desired package state. Each state maps to da_cli operations.
      - C(downloaded) ensures the package is downloaded from the
        public online repository.
      - C(private_download) downloads an unpublished package from
        the Check Point online repository using C(add_private_package).
        The package name must be known but will not appear in public
        package listings.
      - C(imported) imports a package file already on the host filesystem
        into the DA repository. Requires C(location).
      - C(verified) ensures the package passes pre-install verification.
        This operation is informational and does not change system state.
      - C(installed) ensures the package is installed. Automatically runs
        verify before install unless C(verify_before_install) is false.
      - C(upgraded) performs a major version upgrade operation.
        Verify checks C(upgrade.applicable) for eligibility.
      - C(absent) uninstalls an installed package or deletes a downloaded
        package from the local repository.
    type: str
    choices: [downloaded, private_download, imported, verified, installed, upgraded, absent]
    required: true
  location:
    description:
      - Directory path on the remote host where the package file resides.
      - Required when C(state=imported).
      - Despite da_cli documentation suggesting this is optional for
        import operations, it is actually mandatory.
    type: str
  reboot_delay:
    description:
      - Delay in seconds before rebooting after install, upgrade, or uninstall.
      - A minimum value of 30 is strongly recommended. This creates a polling
        window where da_cli emits a reboot-imminent signal before the host
        goes down, allowing the module to return a clean result to Ansible
        rather than losing the SSH connection mid-operation.
      - If set too low or omitted, the host may reboot before the module
        receives a clean result, causing a false failure.
    type: int
    default: 30
  uninstall_method:
    description:
      - Uninstall method when C(state=absent) and the package is installed.
      - C(completely) removes the package entirely.
      - C(last_take) reverts to the previous take or snapshot.
    type: str
    choices: [completely, last_take]
  role:
    description:
      - Machine role for verify and clean_install operations.
    type: str
  refresh:
    description:
      - Run C(check_for_updates) before the operation to sync the local
        package catalog with the Check Point cloud repository.
    type: bool
    default: false
  verify_before_install:
    description:
      - Automatically run verify before install or upgrade.
      - Checks C(install.applicable) for C(state=installed) and
        C(upgrade.applicable) for C(state=upgraded).
      - A verify result indicating the package is already installed
        (DEPENDENCY message-code) is treated as success rather than failure.
    type: bool
    default: true
  poll_interval:
    description:
      - Seconds between status polls for action commands.
    type: int
    default: 15
  timeout:
    description:
      - Maximum seconds to wait for an action to complete.
      - For install and upgrade operations on physical hardware, this may
        need to be increased significantly beyond the default.
    type: int
    default: 900
author:
  - Duane Toler <dtoler@webfargo.com>
"""

EXAMPLES = r"""
# Download a specific package
- name: Download Jumbo HFA T91
  webfargo.check_point.da_package:
    name: "Check_Point_R82_jumbo_hf_main_Bundle_T91_FULL.tgz"
    state: downloaded
    refresh: true

# Download an unpublished (private) package from Check Point cloud
- name: Download private hotfix from CP cloud
  webfargo.check_point.da_package:
    name: "Check_Point_R82_PRIVATE_HF_12345.tgz"
    state: private_download

# Import a package already copied to the host filesystem
- name: Import private hotfix
  webfargo.check_point.da_package:
    name: "custom_hotfix_HF123.tgz"
    state: imported
    location: "/var/tmp"

# Install the auto-detected Recommended Jumbo HFA
- name: Install latest Jumbo HFA
  webfargo.check_point.da_package:
    state: installed
    refresh: true
    timeout: 1800
  register: install_result

# Install a specific package
- name: Install specific Jumbo HFA
  webfargo.check_point.da_package:
    name: "Check_Point_R81_20_JUMBO_HF_MAIN_Bundle_T80_FULL.tgz"
    state: installed
  register: install_result

# Wait for host to come back after reboot
- name: Wait for SSH to go down
  ansible.builtin.wait_for_connection:
    connect_timeout: 3
    delay: 90
    sleep: 10
    timeout: 600
  when: install_result.changed

# Verify only (informational, no state change)
- name: Pre-verify package
  webfargo.check_point.da_package:
    name: "Check_Point_R82_jumbo_hf_main_Bundle_T91_FULL.tgz"
    state: verified
  register: verify_result

- name: Show verify details
  ansible.builtin.debug:
    msg: "Install applicable {{ verify_result.verify_details.install.applicable }}"

# Uninstall a package completely
- name: Uninstall hotfix
  webfargo.check_point.da_package:
    name: "mgmt_wrapper_HOTFIX_R82_JHF_T60_000_MAIN_GA_FULL.tgz"
    state: absent
    uninstall_method: completely
  register: uninstall_result

# Delete a downloaded package from the local repository (does not uninstall)
- name: Remove old Jumbo from repository
  webfargo.check_point.da_package:
    name: "Check_Point_R82_jumbo_hf_main_Bundle_T80_FULL.tgz"
    state: absent
"""

RETURN = r"""
action_id:
  description: The da_cli action ID for the primary operation
  returned: when an action command was executed
  type: str
action_type:
  description: The type of action that was performed
  returned: when an action command was executed
  type: str
package:
  description: Package filename that was operated on
  returned: always
  type: str
status:
  description: Final status of the operation
  returned: always
  type: str
progress:
  description: Final progress percentage
  returned: when an action command was executed
  type: str
verify_details:
  description: >
    Parsed verification results (from the embedded JSON in the Message
    field of verify operations). Contains install/upgrade/clean-install
    applicability and messages.
  returned: when state is verified or verify_before_install runs
  type: dict
auto_selected:
  description: Whether the package was auto-selected (latest Jumbo HFA)
  returned: when name was not specified
  type: bool
"""

import json
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.webfargo.check_point.plugins.module_utils.da_cli import (
    DaCliClient,
    DaCliError,
)


def find_recommended_jumbo(client):
    """Auto-detect the Recommended Jumbo HFA package. Returns filename or None."""
    pkg = client.find_recommended_jumbo()

    return pkg.get("filename") if pkg else None


def get_package_state(client, package_name):
    """Query current state of a package. Returns pkg dict or None."""
    try:
        for pkg in client.get_packages():
            if pkg.get("filename") == package_name:
                return pkg
    except DaCliError:
        pass

    return None


def normalize_pkg_state(current):
    """
    Normalize da_cli's freeform state strings to internal values.

    Known state strings:
      "Installed Successfully"  -> "installed"
      "Available for Install"   -> "available"
      "Available for download"  -> "not_downloaded"
    """
    if not current:
        return "unknown"

    _cs = current.get("state", "").lower()

    if _cs.startswith("installed"):
        return "installed"
    elif "for install" in _cs:
        return "available"
    elif "for download" in _cs:
        return "not_downloaded"

    return "unknown"


def _parse_verify_message(action_result):
    """Extract and parse the embedded JSON from a verify action result."""
    msg = action_result.get("message", "")

    if isinstance(msg, dict):
        return msg

    if isinstance(msg, str) and msg:
        try:
            return json.loads(msg)
        except (json.JSONDecodeError, TypeError):
            return {"raw": msg}

    return {}


def _run_verify(module, client, params, package_name):
    """
    Run verify and return parsed verify_details.
    Raises DaCliError on failure.
    """
    verify_cmd = f"verify package={package_name}"

    if params["role"]:
        verify_cmd += f" role={params['role']}"

    verify_result = client.run_action(
        verify_cmd,
        poll_interval=params["poll_interval"],
        timeout=params["timeout"],
    )

    return _parse_verify_message(verify_result)


def _extract_warnings(verify_details, key):
    """Extract warning messages from verify_details for a given key."""
    warning = verify_details.get(key, {})

    if warning.get("applicable") and warning.get("messages"):
        return [
            m.get("text", "")
            for m in warning["messages"]
            if m.get("text")
        ]

    return []


def state_downloaded(module, client, params, package_name, current, _pkg_state):
    result = {}

    if current and current.get("isInRepository"):
        result["status"] = "already_downloaded"
        result["changed"] = False
    elif module.check_mode:
        result["status"] = "would_download"
        result["changed"] = True
    else:
        action_result = client.run_action(
            f"download package={package_name}",
            poll_interval=params["poll_interval"],
            timeout=params["timeout"],
        )
        result.update(action_result)
        result["changed"] = True

    return result


def state_private_download(module, client, params, package_name, current, _pkg_state):
    result = {}

    if current and current.get("isInRepository"):
        result["status"] = "already_downloaded"
        result["changed"] = False
    elif module.check_mode:
        result["status"] = "would_download_private"
        result["changed"] = True
    else:
        action_result = client.run_action(
            f"add_private_package package={package_name}",
            poll_interval=params["poll_interval"],
            timeout=params["timeout"],
        )
        result.update(action_result)
        result["changed"] = True

    return result


def state_imported(module, client, params, package_name, current, _pkg_state):
    result = {}

    if current and current.get("isInRepository"):
        result["status"] = "already_in_repository"
        result["changed"] = False
    elif module.check_mode:
        result["status"] = "would_import"
        result["changed"] = True
    else:
        action_result = client.run_action(
            f"import package={package_name} location={params['location']}",
            poll_interval=params["poll_interval"],
            timeout=params["timeout"],
        )
        result.update(action_result)
        result["changed"] = True

    return result


def state_verified(module, client, params, package_name, current, _pkg_state):
    result = {}

    if module.check_mode:
        result["status"] = "would_verify"
        result["changed"] = False
        return result

    action_result = client.run_action(
        f"verify package={package_name}"
        + (f" role={params['role']}" if params["role"] else ""),
        poll_interval=params["poll_interval"],
        timeout=params["timeout"],
    )

    result.update(action_result)
    result["changed"] = False
    result["verify_details"] = _parse_verify_message(action_result)

    return result


def state_installed(module, client, params, package_name, current, _pkg_state):
    result = {}

    if _pkg_state == "installed":
        result["status"] = "already_installed"
        result["changed"] = False
        return result

    if module.check_mode:
        result["status"] = "would_install"
        result["changed"] = True
        return result

    # Step 1: Verify (if requested)
    if params["verify_before_install"]:
        try:
            verify_details = _run_verify(module, client, params, package_name)
        except DaCliError:
            recheck = get_package_state(client, package_name)

            if recheck:
                _recheck_cs = recheck.get("state", "").lower()

                if _recheck_cs.startswith("installed"):
                    result["status"] = "already_installed"
                    result["changed"] = False
                    return result
            raise

        result["verify_details"] = verify_details

        install_info = verify_details.get("install", {})

        if install_info and not install_info.get("applicable"):
            msgs = install_info.get("messages", []) or []

            if any(m.get("message-code") == "DEPENDENCY" for m in msgs):
                result["status"] = "already_installed"
                result["changed"] = False
                return result

            module.fail_json(
                msg="Package verification indicates install is not applicable",
                verify_details=verify_details,
            )

        warnings = _extract_warnings(verify_details, "warning-install")

        if warnings:
            result["warnings"] = warnings

    # Step 2: Install
    action_result = client.run_action(
        f"install package={package_name} reboot_delay={params['reboot_delay']}",
        poll_interval=params["poll_interval"],
        timeout=params["timeout"],
    )

    result.update(action_result)
    result["changed"] = True
    return result


def state_upgraded(module, client, params, package_name, current, _pkg_state):
    result = {}

    if module.check_mode:
        result["status"] = "would_upgrade"
        result["changed"] = True
        return result

    if params["verify_before_install"]:
        verify_details = _run_verify(module, client, params, package_name)
        result["verify_details"] = verify_details

        upgrade_info = verify_details.get("upgrade", {})

        if upgrade_info and not upgrade_info.get("applicable"):
            module.fail_json(
                msg="Package verification indicates upgrade is not applicable",
                verify_details=verify_details,
            )

        warnings = _extract_warnings(verify_details, "warning-upgrade")

        if warnings:
            result["warnings"] = warnings

    action_result = client.run_action(
        f"upgrade package={package_name} reboot_delay={params['reboot_delay']}",
        poll_interval=params["poll_interval"],
        timeout=params["timeout"],
        is_upgrade=True,
    )

    result.update(action_result)
    result["changed"] = True
    return result


def state_absent(module, client, params, package_name, current, _pkg_state):
    result = {}

    if not current:
        result["status"] = "not_present"
        result["changed"] = False
        return result

    if _pkg_state == "installed":
        if module.check_mode:
            result["status"] = "would_uninstall"
            result["changed"] = True
            return result

        uninstall_cmd = (
            f"uninstall package={package_name}"
            f" reboot_delay={params['reboot_delay']}"
        )

        if params["uninstall_method"]:
            uninstall_cmd += f" method={params['uninstall_method']}"

        action_result = client.run_action(
            uninstall_cmd,
            poll_interval=params["poll_interval"],
            timeout=params["timeout"],
        )

        result.update(action_result)
        result["changed"] = True

        return result

    # Not installed — delete from repo if locally present
    if _pkg_state == "not_downloaded":
        result["status"] = "not_present"
        result["changed"] = False

        return result

    if module.check_mode:
        result["status"] = "would_delete"
        result["changed"] = True

        return result

    action_result = client.run_action(
        f"delete package={package_name}",
        poll_interval=params["poll_interval"],
        timeout=params["timeout"],
    )

    result.update(action_result)
    result["changed"] = True
    return result


STATE_HANDLERS = {
    "downloaded": state_downloaded,
    "private_download": state_private_download,
    "imported": state_imported,
    "verified": state_verified,
    "installed": state_installed,
    "upgraded": state_upgraded,
    "absent": state_absent,
}


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str"),
            state=dict(
                type="str",
                required=True,
                choices=list(STATE_HANDLERS.keys()),
            ),
            location=dict(type="str"),
            reboot_delay=dict(type="int", default=30),
            uninstall_method=dict(
                type="str",
                choices=["completely", "last_take"],
            ),
            role=dict(type="str"),
            refresh=dict(type="bool", default=False),
            verify_before_install=dict(type="bool", default=True),
            poll_interval=dict(type="int", default=15),
            timeout=dict(type="int", default=900),
        ),
        required_if=[
            ("state", "imported", ["name", "location"]),
        ],
        supports_check_mode=True,
    )

    params = module.params
    client = DaCliClient(module, timeout=params["timeout"])
    state = params["state"]
    package_name = params["name"]

    result = {
        "changed": False,
        "auto_selected": False,
    }

    try:
        # Auto-detect package name if not provided
        if not package_name and state in ("downloaded", "verified", "installed"):
            if params["refresh"] and not module.check_mode:
                client.check_for_updates(timeout=params["timeout"])
                params["refresh"] = False

            package_name = find_recommended_jumbo(client)

            if not package_name:
                module.fail_json(
                    msg="No package name provided and could not auto-detect "
                        "Recommended Jumbo HFA (no uninstalled package with "
                        "tag.importance=='latest' and category=='jumbo' found)"
                )

            result["auto_selected"] = True

        if not package_name:
            module.fail_json(msg="Package name is required for this operation")

        result["package"] = package_name

        # Optional refresh
        if params["refresh"] and not module.check_mode:
            client.check_for_updates(timeout=params["timeout"])

        # Get current package state for idempotency
        current = get_package_state(client, package_name)
        _pkg_state = normalize_pkg_state(current)

        # Dispatch to state handler
        result.update(
            STATE_HANDLERS[state](module, client, params, package_name, current, _pkg_state)
        )

    except DaCliError as e:
        module.fail_json(msg=str(e), package=package_name)

    module.exit_json(**result)


if __name__ == "__main__":
    main()
