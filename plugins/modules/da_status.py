#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Webfargo Data Security, Inc.
# GNU General Public License v3.0+

DOCUMENTATION = r"""
---
module: da_status
short_description: Get Check Point Deployment Agent status
description:
  - Query the Deployment Agent (da_cli) for service status, build
    number, and pending reboot state.
  - The DA build number comes from C(da_status) (the C(DABuildNumber)
    field), not from C(get_version) which returns a useless static "1".
  - This is a read-only module that never makes changes.
options:
  wait_for_ready:
    description:
      - If true, poll until the DA service is fully ready and idle
        (DAService State=ready, Installation in Progress=false,
        Update Status=done).
      - Useful after running check_for_updates or before starting
        a new operation.
    type: bool
    default: false
  timeout:
    description: Command timeout in seconds.
    type: int
    default: 120
author:
  - Duane Toler <dtoler@webfargo.com>
"""

EXAMPLES = r"""
- name: Get DA status
  webfargo.check_point.da_status:
  register: da

- name: Show DA build number
  debug:
    msg: "DA build: {{ da.build_number }}"

- name: Check if reboot is pending
  debug:
    msg: "Reboot pending!"
  when: da.pending_reboot

- name: Wait for DA to be fully ready
  webfargo.check_point.da_status:
    wait_for_ready: true
    timeout: 300
"""

RETURN = r"""
da_status:
  description: Full da_status response (raw keys preserved)
  returned: always
  type: dict
  sample:
    Action ID: "0"
    DABuildNumber: "2672"
    DAService State: ready
    Installation in Progress: false
    Last Update Time: "Wed Feb 11 14:55:28 2026"
    New DA Availability: up to date
    Update Status: done
build_number:
  description: DA build number (from DABuildNumber, not get_version)
  returned: always
  type: str
service_state:
  description: DAService State value
  returned: always
  type: str
ready:
  description: >
    Whether DA is fully ready (service ready, no installation in
    progress, update status done)
  returned: always
  type: bool
pending_reboot:
  description: Whether a reboot is pending
  returned: always
  type: bool
installation_in_progress:
  description: Whether an installation is currently in progress
  returned: always
  type: bool
update_status:
  description: Current update status string
  returned: always
  type: str
"""

import time
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.webfargo.check_point.plugins.module_utils.da_cli import (
    DaCliClient,
    DaCliError,
)


def get_status(client):
    """Fetch da_status and build result fields."""
    status = client.get_da_status()

    return {
        "da_status": status,
        "build_number": client.get_build_number() or "unknown",
        "service_state": status.get("DAService State", "unknown"),
        "installation_in_progress": status.get("Installation in Progress", False),
        "update_status": status.get("Update Status", "unknown"),
        "ready": (
            status.get("DAService State") == "ready"
            and not status.get("Installation in Progress", False)
            and status.get("Update Status") == "done"
        ),
    }


def get_pending_reboot(client):
    """Check pending reboot state. Returns True/False/None for older builds."""
    try:
        reboot_data = client.run("is_pending_reboot", raw=True)
        msg = reboot_data.get("Message", "")

        return msg.lower() != "no reboot"
    except DaCliError:
        return None


def wait_until_ready(module, client):
    """Poll until DA is ready or timeout. Calls fail_json on timeout."""
    timeout = module.params["timeout"]
    elapsed = 0
    poll_interval = 10

    while elapsed < timeout:
        if client.is_ready():
            return

        time.sleep(poll_interval)
        elapsed += poll_interval
    else:
        status = client.get_da_status()

        module.fail_json(
            msg=f"DA not ready after {timeout}s "
                f"(state: {status.get('DAService State')}, "
                f"update: {status.get('Update Status')})"
        )

def main():
    module = AnsibleModule(
        argument_spec=dict(
            wait_for_ready=dict(type="bool", default=False),
            timeout=dict(type="int", default=120),
        ),
        supports_check_mode=True,
    )

    client = DaCliClient(module, timeout=module.params["timeout"])
    result = {"changed": False}

    try:
        if module.params["wait_for_ready"] and not module.check_mode:
            wait_until_ready(module, client)

        result.update(get_status(client))
        result["pending_reboot"] = get_pending_reboot(client)

    except DaCliError as e:
        module.fail_json(msg=str(e))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
