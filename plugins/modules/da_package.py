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
  - If C(name) is omitted for install/verify operations, the module
    auto-detects the latest Jumbo HFA from the local repository.
  - Supports check mode for all operations.
options:
  name:
    description:
      - Package filename.
      - If omitted for C(install), C(verify), or C(download) operations,
        the module auto-selects the latest Jumbo HFA
        (tag.importance == "latest").
    type: str
  state:
    description:
      - Desired package state. Each state maps to da_cli operations.
      - C(downloaded) ensures the package is downloaded from the
        public online repository.
      - C(private_download) downloads an unpublished package from
        Check Point's online repository using C(add_private_package).
        The package name must be known but won't appear in public
        package listings.
      - C(imported) imports a package file already on the host filesystem
        into the DA repository (requires C(location)).
      - C(verified) ensures the package passes pre-install verification.
      - C(installed) ensures the package is installed (implies download
        and verify if needed).
      - C(upgraded) performs an upgrade operation (for major version jumps).
        Verify checks C(upgrade.applicable) for eligibility.
      - C(absent) uninstalls or deletes the package.
      - Note: C(clean_install) is not a separate state; use
        C(da_command) with C(command="clean_install package=...") for
        fresh installs of version upgrade packages.
    type: str
    choices: [downloaded, private_download, imported, verified, installed, upgraded, absent]
    required: true
  location:
    description:
      - Directory path on the remote host where the package file resides.
      - Required when C(state=imported).
      - Despite da_cli documentation suggesting this is optional for
        C(import), it is actually mandatory.
    type: str
  reboot_delay:
    description:
      - Delay in seconds before rebooting after install/upgrade/uninstall.
      - Only applicable for operations that trigger a reboot.
    type: int
  uninstall_method:
    description:
      - Uninstall method when C(state=absent).
      - C(completely) removes the package entirely.
      - C(last_take) reverts to the previous take/snapshot.
    type: str
    choices: [completely, last_take]
  role:
    description:
      - Machine role for verify and clean_install operations.
    type: str
  refresh:
    description:
      - Run C(check_for_updates) before the operation.
    type: bool
    default: false
  verify_before_install:
    description:
      - Automatically run verify before install.
      - Only relevant when C(state=installed).
    type: bool
    default: true
  poll_interval:
    description: Seconds between status polls for action commands.
    type: int
    default: 15
  timeout:
    description: Maximum seconds to wait for an action to complete.
    type: int
    default: 900
author:
  - Duane Toler <dtoler@webfargo.com>
"""

EXAMPLES = r"""
# Download a specific package
- name: Download Jumbo HFA T84
  webfargo.check_point.da_package:
    name: "Check_Point_R81_20_JUMBO_HF_MAIN_Bundle_T84_FULL.tgz"
    state: downloaded
    refresh: true

# Download an unpublished (private) package from Check Point Cloud
- name: Download private hotfix from CP cloud
  webfargo.check_point.da_package:
    name: "Check_Point_R81_20_PRIVATE_HF_12345.tgz"
    state: private_download

# Import a package that was SCP'd to the host
- name: Import private hotfix
  webfargo.check_point.da_package:
    name: "custom_hotfix_HF123.tgz"
    state: imported
    location: "/var/tmp"

# Install latest Jumbo HFA (auto-detect)
- name: Install latest Jumbo HFA
  webfargo.check_point.da_package:
    state: installed
    refresh: true
    timeout: 1800
  register: install_result

# Install a specific package
- name: Install specific Jumbo
  webfargo.check_point.da_package:
    name: "Check_Point_R81_20_JUMBO_HF_MAIN_Bundle_T84_FULL.tgz"
    state: installed
    reboot_delay: 60

# Verify only (dry-run before install)
- name: Pre-verify package
  webfargo.check_point.da_package:
    name: "Check_Point_R81_20_JUMBO_HF_MAIN_Bundle_T84_FULL.tgz"
    state: verified
  register: verify_result

- name: Check verify details
  debug:
    msg: "Install applicable: {{ verify_result.verify_details.install.applicable }}"

# Uninstall a package
- name: Remove old Jumbo
  webfargo.check_point.da_package:
    name: "Check_Point_R81_20_JUMBO_HF_MAIN_Bundle_T80_FULL.tgz"
    state: absent
    uninstall_method: completely

# Delete old package from repository (doesn't uninstall)
- name: Clean up old packages
  webfargo.check_point.da_package:
    name: "Check_Point_R81_20_JUMBO_HF_MAIN_Bundle_T80_FULL.tgz"
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


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str"),
            state=dict(
                type="str",
                required=True,
                choices=[
                    "downloaded", "private_download", "imported",
                    "verified", "installed", "upgraded", "absent",
                ],
            ),
            location=dict(type="str"),
            reboot_delay=dict(type="int"),
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
    poll_interval = params["poll_interval"]
    timeout = params["timeout"]
    state = params["state"]
    package_name = params["name"]
    auto_selected = False

    result = {
        "changed": False,
        "auto_selected": False,
    }

    try:
        # --- Auto-detect package name if not provided ---
        if not package_name and state in ("downloaded", "verified", "installed"):
            if params["refresh"] and not module.check_mode:
                client.check_for_updates(timeout=params["timeout"])
                # Mark refresh done so we don't do it twice
                params["refresh"] = False

            package_name = find_recommended_jumbo(client)
            if not package_name:
                module.fail_json(
                    msg="No package name provided and could not auto-detect "
                        "Recommended Jumbo HFA (no uninstalled package with "
                        "tag.importance=='latest' and category=='jumbo' found)"
                )
            auto_selected = True
            result["auto_selected"] = True

        if not package_name:
            module.fail_json(msg="Package name is required for this operation")

        result["package"] = package_name

        # --- Optional refresh ---
        if params["refresh"] and not module.check_mode:
            client.check_for_updates(timeout=params["timeout"])

        # --- Get current package state for idempotency ---
        current = get_package_state(client, package_name)
        current_state = current.get("state", "unknown") if current else "unknown"

        # =====================================================
        # STATE: downloaded
        # =====================================================
        if state == "downloaded":
            # isInRepository indicates the package file is locally available
            if current and (current.get("isInRepository") or
                           current_state in ("downloaded", "installed")):
                result["status"] = "already_downloaded"
                result["changed"] = False
            elif module.check_mode:
                result["status"] = "would_download"
                result["changed"] = True
            else:
                action_result = client.run_action(
                    f"download package={package_name}",
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
                result.update(action_result)
                result["changed"] = True

        # =====================================================
        # STATE: private_download
        # =====================================================
        elif state == "private_download":
            # add_private_package downloads unpublished packages
            # from Check Point's online repo by known name
            if current and (current.get("isInRepository") or
                           current_state in ("downloaded", "installed")):
                result["status"] = "already_downloaded"
                result["changed"] = False
            elif module.check_mode:
                result["status"] = "would_download_private"
                result["changed"] = True
            else:
                action_result = client.run_action(
                    f"add_private_package package={package_name}",
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
                result.update(action_result)
                result["changed"] = True

        # =====================================================
        # STATE: imported
        # =====================================================
        elif state == "imported":
            if current and current.get("isInRepository"):
                result["status"] = "already_in_repository"
                result["changed"] = False
            elif module.check_mode:
                result["status"] = "would_import"
                result["changed"] = True
            else:
                location = params["location"]
                action_result = client.run_action(
                    f"import package={package_name} location={location}",
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
                result.update(action_result)
                result["changed"] = True

        # =====================================================
        # STATE: verified
        # =====================================================
        elif state == "verified":
            if module.check_mode:
                result["status"] = "would_verify"
                result["changed"] = False  # verify is non-destructive
            else:
                cmd = f"verify package={package_name}"
                if params["role"]:
                    cmd += f" role={params['role']}"

                action_result = client.run_action(
                    cmd,
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
                result.update(action_result)
                # Verify doesn't change state; it's informational
                result["changed"] = False

                # Extract embedded verify JSON from Message
                msg = action_result.get("message", "")
                if isinstance(msg, dict):
                    result["verify_details"] = msg
                elif isinstance(msg, str) and msg:
                    try:
                        result["verify_details"] = json.loads(msg)
                    except (json.JSONDecodeError, TypeError):
                        result["verify_details"] = {"raw": msg}

        # =====================================================
        # STATE: installed
        # =====================================================
        elif state == "installed":
            if current and current_state == "installed":
                result["status"] = "already_installed"
                result["changed"] = False
            elif module.check_mode:
                result["status"] = "would_install"
                result["changed"] = True
            else:
                # Step 1: Verify (if requested)
                if params["verify_before_install"]:
                    verify_cmd = f"verify package={package_name}"
                    if params["role"]:
                        verify_cmd += f" role={params['role']}"

                    try:
                        verify_result = client.run_action(
                            verify_cmd,
                            poll_interval=poll_interval,
                            timeout=timeout,
                        )
                    except DaCliError as ve:
                        # Verify can "fail" if package is already installed
                        # (message-code DEPENDENCY). Check for this case.
                        # Re-query package state to confirm.
                        recheck = get_package_state(client, package_name)
                        if recheck and recheck.get("state") == "installed":
                            result["status"] = "already_installed"
                            result["changed"] = False
                            module.exit_json(**result)
                        raise  # Real failure, propagate

                    # Parse verify Message for install applicability
                    msg = verify_result.get("message", "")
                    verify_details = {}
                    if isinstance(msg, dict):
                        verify_details = msg
                    elif isinstance(msg, str) and msg:
                        try:
                            verify_details = json.loads(msg)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    result["verify_details"] = verify_details

                    # Check if install is applicable
                    # For Jumbo HFA packages, install.applicable is the
                    # relevant flag. For version upgrade packages,
                    # install.applicable will be false — those use
                    # state=upgraded which checks upgrade.applicable instead.
                    install_info = verify_details.get("install", {})
                    if install_info and not install_info.get("applicable"):
                        # Check if already installed (DEPENDENCY)
                        msgs = install_info.get("messages", []) or []
                        already_installed = any(
                            m.get("message-code") == "DEPENDENCY"
                            for m in msgs
                        )
                        if already_installed:
                            result["status"] = "already_installed"
                            result["changed"] = False
                            module.exit_json(**result)

                        module.fail_json(
                            msg="Package verification indicates install "
                                "is not applicable",
                            verify_details=verify_details,
                        )

                    # Surface install warnings if present
                    warning_install = verify_details.get(
                        "warning-install", {}
                    )
                    if (warning_install.get("applicable") and
                            warning_install.get("messages")):
                        result["warnings"] = [
                            m.get("text", "")
                            for m in warning_install["messages"]
                            if m.get("text")
                        ]

                # Step 2: Install
                install_cmd = f"install package={package_name}"
                if params["reboot_delay"] is not None:
                    install_cmd += f" reboot_delay={params['reboot_delay']}"

                action_result = client.run_action(
                    install_cmd,
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
                result.update(action_result)
                result["changed"] = True

        # =====================================================
        # STATE: upgraded
        # =====================================================
        elif state == "upgraded":
            if module.check_mode:
                result["status"] = "would_upgrade"
                result["changed"] = True
            else:
                # Verify first if requested
                if params["verify_before_install"]:
                    verify_cmd = f"verify package={package_name}"
                    if params["role"]:
                        verify_cmd += f" role={params['role']}"

                    verify_result = client.run_action(
                        verify_cmd,
                        poll_interval=poll_interval,
                        timeout=timeout,
                    )

                    msg = verify_result.get("message", "")
                    verify_details = {}
                    if isinstance(msg, dict):
                        verify_details = msg
                    elif isinstance(msg, str) and msg:
                        try:
                            verify_details = json.loads(msg)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    result["verify_details"] = verify_details

                    upgrade_info = verify_details.get("upgrade", {})
                    if upgrade_info and not upgrade_info.get("applicable"):
                        module.fail_json(
                            msg="Package verification indicates upgrade "
                                "is not applicable",
                            verify_details=verify_details,
                        )

                    # Surface upgrade warnings if present
                    warning_upgrade = verify_details.get(
                        "warning-upgrade", {}
                    )
                    if (warning_upgrade.get("applicable") and
                            warning_upgrade.get("messages")):
                        result["warnings"] = [
                            m.get("text", "")
                            for m in warning_upgrade["messages"]
                            if m.get("text")
                        ]

                # Upgrade: uses is_upgrade=True to handle the
                # reboot-during-progress quirk where Status stays
                # "in progress" at Progress 100, system reboots,
                # Progress drops back, then climbs to 100 again.
                # This needs a much longer timeout than install.
                upgrade_cmd = f"upgrade package={package_name}"
                if params["reboot_delay"] is not None:
                    upgrade_cmd += f" reboot_delay={params['reboot_delay']}"

                action_result = client.run_action(
                    upgrade_cmd,
                    poll_interval=poll_interval,
                    timeout=timeout,
                    is_upgrade=True,
                )
                result.update(action_result)
                result["changed"] = True

        # =====================================================
        # STATE: absent
        # =====================================================
        elif state == "absent":
            if not current:
                result["status"] = "not_present"
                result["changed"] = False
            elif current_state == "installed":
                # Uninstall first
                if module.check_mode:
                    result["status"] = "would_uninstall"
                    result["changed"] = True
                else:
                    uninstall_cmd = f"uninstall package={package_name}"
                    if params["reboot_delay"] is not None:
                        uninstall_cmd += (
                            f" reboot_delay={params['reboot_delay']}"
                        )
                    if params["uninstall_method"]:
                        uninstall_cmd += (
                            f" method={params['uninstall_method']}"
                        )

                    action_result = client.run_action(
                        uninstall_cmd,
                        poll_interval=poll_interval,
                        timeout=timeout,
                    )
                    result.update(action_result)
                    result["changed"] = True
            else:
                # Package exists but isn't installed; delete from repo
                if module.check_mode:
                    result["status"] = "would_delete"
                    result["changed"] = True
                else:
                    action_result = client.run_action(
                        f"delete package={package_name}",
                        poll_interval=poll_interval,
                        timeout=timeout,
                    )
                    result.update(action_result)
                    result["changed"] = True

    except DaCliError as e:
        module.fail_json(msg=str(e), package=package_name)

    module.exit_json(**result)


if __name__ == "__main__":
    main()
