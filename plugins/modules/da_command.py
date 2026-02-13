#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Webfargo Data Security, Inc.
# GNU General Public License v3.0+

DOCUMENTATION = r"""
---
module: da_command
short_description: Run arbitrary da_cli commands
description:
  - Execute any da_cli subcommand and return the JSON response.
  - If the command is an action command (returns a real Action ID),
    optionally poll until completion.
  - This is the escape hatch for operations not covered by the
    higher-level modules.
options:
  command:
    description:
      - The da_cli subcommand and arguments to execute.
      - Do not include the C(da_cli) prefix.
    type: str
    required: true
  wait:
    description:
      - If true and the command returns an Action ID, poll
        until the action completes.
    type: bool
    default: true
  poll_interval:
    description: Seconds between status polls.
    type: int
    default: 10
  timeout:
    description: Maximum seconds to wait for completion.
    type: int
    default: 300
  parse_message:
    description:
      - If true, attempt to parse embedded JSON in the Message field.
    type: bool
    default: true
author:
  - Duane Toler <dtoler@webfargo.com>
"""

EXAMPLES = r"""
# Run check_for_updates
- name: Sync with Check Point update servers
  webfargo.check_point.da_command:
    command: check_for_updates

# Collect DA logs
- name: Collect deployment agent logs
  webfargo.check_point.da_command:
    command: "collect_logs destination=/var/tmp/da_logs.tgz"

# Manage DA configuration
- name: Show DA configuration
  webfargo.check_point.da_command:
    command: "edit_configuration operation=show_config"
  register: da_config

# Cancel a stuck operation
- name: Cancel stuck download
  webfargo.check_point.da_command:
    command: "cancel package=Some_Package.tgz"
    wait: true

# Complete a pending operation
- name: Complete pending action
  webfargo.check_point.da_command:
    command: "complete package=Some_Package.tgz"
    wait: true
"""

RETURN = r"""
response:
  description: Parsed JSON response from da_cli
  returned: always
  type: dict
action_id:
  description: Action ID if this was an action command
  returned: when command is an action command
  type: str
is_action:
  description: Whether this was an action command (Action ID != -1)
  returned: always
  type: bool
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.webfargo.check_point.plugins.module_utils.da_cli import (
    DaCliClient,
    DaCliError,
)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            command=dict(type="str", required=True),
            wait=dict(type="bool", default=True),
            poll_interval=dict(type="int", default=10),
            timeout=dict(type="int", default=300),
            parse_message=dict(type="bool", default=True),
        ),
        supports_check_mode=False,
    )

    params = module.params
    client = DaCliClient(module, timeout=params["timeout"])

    try:
        if params["wait"]:
            response = client.run_action(
                params["command"],
                poll_interval=params["poll_interval"],
                timeout=params["timeout"],
            )
        else:
            response = client.run(params["command"])

        if params["parse_message"]:
            response = client.parse_embedded_message(response)

        is_action = client.is_action_command(response)

        result = {
            "changed": is_action,  # Assume action commands change state
            "response": response,
            "is_action": is_action,
        }

        if is_action:
            result["action_id"] = response.get(
                "action_id", response.get("Action ID")
            )

    except DaCliError as e:
        module.fail_json(msg=str(e))

    module.exit_json(**result)


if __name__ == "__main__":
    main()


