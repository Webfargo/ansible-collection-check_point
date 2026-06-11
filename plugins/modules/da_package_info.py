#!/usr/bin/python
# -*- coding: utf-8 -*-
# plugins/modules/da_package_info.py

# Copyright: (c) 2026, Webfargo Data Security, Inc.
# GNU General Public License v3.0+

DOCUMENTATION = r"""
---
module: da_package_info
short_description: Query Check Point Deployment Agent package information
description:
  - Retrieve package information from the Deployment Agent.
  - Can list all packages, filter by status or category, query a single
    package by name, or find the Recommended or Latest Jumbo HFA
    automatically using the C(jumbo) parameter.
  - This is a read-only module that never makes changes.
options:
  name:
    description:
      - Specific package name to query.
      - Returns a single package dict.
      - Mutually exclusive with C(status), C(jumbo), and C(category).
    type: str
  status:
    description:
      - Filter packages by status. This is a pass-through to
        C(da_cli packages_info status=<value>).
      - Note that C(status=recommended) returns packages of ANY type
        that Check Point has marked as recommended, including major
        version upgrades. To specifically find the Recommended Jumbo
        HFA, use C(jumbo=recommended) instead.
      - Mutually exclusive with C(name), C(jumbo), and C(category).
    type: str
    choices: [all, available, available_for_download, available_for_install,
              installed, recommended, visible]
    default: all
  jumbo:
    description:
      - Select a Jumbo HFA package by release train.
      - C(recommended) finds the stable, production-ready Jumbo HFA.
        Check Point internally marks this with C(tag.importance == "latest")
        (confusing, but that is their convention). Only returns uninstalled
        packages; if the current Recommended Jumbo is already installed
        and no newer one has been tagged, C(found) will be C(false).
      - C(latest) finds the Latest (beta/pre-release) Jumbo HFA. This is
        the public beta train — the next package that may eventually become
        the Recommended release. These packages have C(category == "jumbo")
        but do NOT have C(tag.importance) set. Not every version has a
        Latest package available; when none exists, C(found) will be
        C(false). If multiple candidates exist, returns the one with the
        highest C(build) number.
      - The C(isHfa) field on package objects is NOT reliable for
        identifying Jumbo HFA packages. The module uses C(category)
        and C(tag.importance) instead.
      - Mutually exclusive with C(name), C(status), and C(category).
    type: str
    choices: [recommended, latest]
  category:
    description:
      - Filter packages by category type.
      - C(jumbo) returns all Jumbo HFA packages (installed and available).
      - C(major) returns major version upgrade packages.
      - C(misc) returns miscellaneous packages (custom hotfixes,
        auto-installed tools). These are typically not user-initiated.
      - Mutually exclusive with C(name), C(jumbo), and C(status).
    type: str
    choices: [jumbo, major, misc]
  refresh:
    description:
      - Run C(check_for_updates) before querying packages to ensure
        the local repository metadata is synced with Check Point servers.
      - Should always be set to C(true) when using C(jumbo), as the
        tag and package availability are only current after a metadata
        refresh.
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
- name: List all packages
  webfargo.check_point.da_package_info:
  register: all_packages

- name: List installed packages
  webfargo.check_point.da_package_info:
    status: installed
  register: installed

- name: Get info on a specific package
  webfargo.check_point.da_package_info:
    name: "Check_Point_R82_jumbo_hf_main_Bundle_T60_FULL.tgz"
  register: pkg

- name: Find the Recommended Jumbo HFA
  webfargo.check_point.da_package_info:
    jumbo: recommended
    refresh: true
  register: jumbo

- name: Show Recommended Jumbo
  debug:
    msg: "Recommended: {{ jumbo.package.filename }}"
  when: jumbo.found

- name: Find the Latest (beta) Jumbo HFA
  webfargo.check_point.da_package_info:
    jumbo: latest
    refresh: true
  register: jumbo_beta

- name: Show Latest Jumbo (may not exist)
  debug:
    msg: "Latest: {{ jumbo_beta.package.filename }}"
  when: jumbo_beta.found

- name: List all Jumbo HFA packages
  webfargo.check_point.da_package_info:
    category: jumbo
  register: all_jumbos

- name: List major version upgrade packages
  webfargo.check_point.da_package_info:
    category: major
  register: upgrades
"""

RETURN = r"""
packages:
  description: List of packages matching the query
  returned: when listing packages (status, category, or default)
  type: list
  elements: dict
package:
  description: Single package info
  returned: when name or jumbo is specified
  type: dict
found:
  description: Whether a matching package was found
  returned: always
  type: bool
count:
  description: Number of packages returned
  returned: when listing packages (status, category, or default)
  type: int
"""

import json
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.webfargo.check_point.plugins.module_utils.da_cli import (
    DaCliClient,
    DaCliError,
)


def query_by_name(module, client):
    pkg_name = module.params["name"]

    try:
        data = client.run(f"package_info package={pkg_name}", raw=True)
        return {
            "package": data,
            "found": True,
        }
    except DaCliError as e:
        # da_cli returns rc=3 with a JSON "No such package" message
        # when the package name is not found. Treat as not-found rather
        # than a hard failure.
        if e.stdout:
            try:
                data = json.loads(e.stdout)
                msg = data.get("Message", "")

                if msg.lower().startswith("no such package"):
                    module.fail_json(
                        msg=f"Package not found in repository: {pkg_name}",
                        package=pkg_name,
                    )
            except (json.JSONDecodeError, TypeError):
                pass
        raise

def query_by_jumbo(module, client):
    if module.params["jumbo"] == "recommended":
        jumbo = client.find_recommended_jumbo()
    else:
        jumbo = client.find_latest_jumbo()

    if jumbo:
        return {
            "package": jumbo,
            "found": True,
        }

    return {
        "package": {},
        "found": False,
    }


def query_by_category(module, client):
    data = client.run("packages_info", raw=True)
    packages = [
        pkg for pkg in data.get("packages", [])
        if pkg.get("category") == module.params["category"]
    ]

    return {
        "packages": packages,
        "count": len(packages),
        "found": len(packages) > 0,
    }


def query_by_status(module, client):
    status = module.params["status"] or "all"
    cmd = "packages_info"

    if status != "all":
        cmd += f" status={status}"

    data = client.run(cmd, raw=True)
    packages = data.get("packages", [])

    return {
        "packages": packages,
        "count": data.get("numberOfPackages", len(packages)),
        "found": len(packages) > 0,
    }


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str"),
            status=dict(
                type="str",
                choices=[
                    "all", "available", "available_for_download",
                    "available_for_install", "installed",
                    "recommended", "visible",
                ],
                default=None,
            ),
            jumbo=dict(
                type="str",
                choices=["recommended", "latest"],
            ),
            category=dict(
                type="str",
                choices=["jumbo", "major", "misc"],
            ),
            refresh=dict(type="bool", default=False),
            timeout=dict(type="int", default=120),
        ),
        mutually_exclusive=[
            ("name", "status"),
            ("name", "jumbo"),
            ("name", "category"),
            ("jumbo", "status"),
            ("jumbo", "category"),
            ("category", "status"),
        ],
        supports_check_mode=True,
    )

    client = DaCliClient(module, timeout=module.params["timeout"])
    result = {"changed": False}

    try:
        if module.params["refresh"] and not module.check_mode:
            client.check_for_updates(timeout=module.params["timeout"])

        if module.params["name"]:
            result.update(query_by_name(module, client))
        elif module.params["jumbo"]:
            result.update(query_by_jumbo(module, client))
        elif module.params["category"]:
            result.update(query_by_category(module, client))
        else:
            result.update(query_by_status(module, client))

    except DaCliError as e:
        module.fail_json(msg=str(e))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
