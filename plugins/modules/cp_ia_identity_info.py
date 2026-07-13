#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Webfargo Data Security, Inc.
# GNU General Public License v3.0+ (see https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: cp_ia_identity_info
short_description: Query Check Point Identity Awareness associations for one IP via the Identity Web API
version_added: "1.0.0"
description:
  - Talks directly to a Check Point Security Gateway's Identity Awareness Web
    API (C(_IA_API)) to run C(show-identity) for a single IP address.
  - There is no bulk/plural "show-identities" endpoint, so I(ip_address) is
    always required and this module only ever returns information for one
    address per call.
  - This module never reports C(changed) since it is read-only.
options:
  ia_host:
    description:
      - IP address or FQDN of the Security Gateway (or cluster VIP) running the
        Identity Awareness Web API.
    required: true
    type: str
  ia_port:
    description:
      - TCP port the Identity Awareness Web API is listening on.
    type: int
    default: 443
  shared_secret:
    description:
      - The shared secret configured for this Identity Web API client in
        SmartConsole on the gateway object.
    required: true
    type: str
  validate_certs:
    description:
      - Whether to validate the gateway's TLS certificate. Gateways typically
        present a self-signed certificate, so this defaults to C(false).
    type: bool
    default: false
  ip_address:
    description:
      - The IP address (IPv4 or IPv6) to query associations for.
    required: true
    type: str
author:
  - Duane Toler <dtoler@webfargo.com>
'''

EXAMPLES = r'''
- name: Look up current identity associations for an IP
  webfargo.check_point.cp_ia_identity_info:
    ia_host: "{{ ia_mgmt_host }}"
    shared_secret: "{{ identity_api_secret }}"
    ip_address: "10.10.5.23"
  register: id_result

- name: Show whether any records were found
  ansible.builtin.debug:
    msg: "{{ id_result.identity_info.found }} ({{ id_result.identity_info.record_count }} records)"

- name: Show combined Access Roles and the first identified username, if any
  ansible.builtin.debug:
    msg: "roles={{ id_result.identity_info.combined_roles }} user={{ id_result.identity_info.users[0].user }}"
  when: id_result.identity_info.found
'''

RETURN = r'''
identity_info:
  description: Parsed information about the queried IP address.
  type: dict
  returned: always
  contains:
    ip_address:
      description: The IP address that was queried (echoed back from the gateway's C(ipv4-address)/C(ipv6-address) field when present).
      type: str
    found:
      description: Whether the gateway reported at least one matching user record.
      type: bool
    record_count:
      description: Number of user records the gateway reported, parsed from the C(message) text (Check Point's documented wording is "total N user records were found.").
      type: int
    message:
      description: Raw message text returned by the gateway.
      type: str
    domain:
      description: Domain of the identified user/machine, when returned.
      type: str
    machine:
      description: Computer name associated with this IP, when available.
      type: str
    machine_groups:
      description: List of computer groups for the associated machine, when available.
      type: list
    machine_identity_source:
      description: Identity source that authenticated the machine session, when available.
      type: str
    combined_roles:
      description: List of all Access Roles calculated for this IP, combining user and machine roles.
      type: list
    users:
      description:
        - List of user identity records found on this IP. Each Check Point gateway version
          may include slightly different sub-fields; the documented ones are shown below.
      type: list
      elements: dict
      contains:
        user:
          description: Username or full name of the identified user.
          type: str
        groups:
          description: List of groups the user belongs to.
          type: list
        roles:
          description: List of Access Roles calculated for this user.
          type: list
        identity-source:
          description: Identity source that authenticated this user (for example C(AD Query) or C(Identity Awareness API)).
          type: str
    raw:
      description: The full, unmodified JSON response body from the gateway, as a fallback for any field not otherwise surfaced above.
      type: dict
http_status:
  description: HTTP status code returned by the gateway.
  type: int
  returned: always
'''

import json
import re

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import fetch_url

RECORD_COUNT_RE = re.compile(r'total\s+(\d+)\s+user records? were found', re.IGNORECASE)


def main():
    argument_spec = dict(
        ia_host=dict(type='str', required=True),
        ia_port=dict(type='int', default=443),
        shared_secret=dict(type='str', required=True, no_log=True),
        validate_certs=dict(type='bool', default=False),
        ip_address=dict(type='str', required=True),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    body = {
        'shared-secret': module.params['shared_secret'],
        'ip-address': module.params['ip_address'],
    }

    url = "https://{0}:{1}/_IA_API/v1.0/show-identity".format(
        module.params['ia_host'], module.params['ia_port']
    )

    response, info = fetch_url(
        module,
        url,
        data=json.dumps(body),
        method='POST',
        headers={'Content-Type': 'application/json'},
    )

    status = info.get('status', -1)
    raw = None
    parsed = None
    if response is not None:
        raw = response.read()
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None

    if status != 200:
        if isinstance(parsed, dict):
            module.fail_json(
                msg="show-identity call failed with HTTP {0}: {1}".format(
                    status, parsed.get('message', info.get('msg'))
                ),
                http_status=status,
                response=parsed,
                code=parsed.get('code'),
                warnings_from_gateway=parsed.get('warnings'),
            )
        module.fail_json(
            msg="show-identity call failed with HTTP {0}: {1}".format(status, info.get('msg', raw)),
            http_status=status,
            response=parsed,
        )

    message = None
    ip_echo = None
    record_count = None
    found = False

    if isinstance(parsed, dict):
        message = parsed.get('message')
        ip_echo = parsed.get('ipv4-address') or parsed.get('ipv6-address')
        # ipv4-address is documented as a plain string, but at least one
        # published "no records found" example returns it as a single-element
        # list - normalize either shape to a plain string here.
        if isinstance(ip_echo, list):
            ip_echo = ip_echo[0] if ip_echo else None
        if message:
            m = RECORD_COUNT_RE.search(message)
            if m:
                record_count = int(m.group(1))
                found = record_count > 0

    identity_info = {
        'ip_address': ip_echo or module.params['ip_address'],
        'found': found,
        'record_count': record_count,
        'message': message,
        'domain': parsed.get('domain') if isinstance(parsed, dict) else None,
        'machine': parsed.get('machine') if isinstance(parsed, dict) else None,
        'machine_groups': parsed.get('machine-groups') if isinstance(parsed, dict) else None,
        'machine_identity_source': parsed.get('machine-identity-source') if isinstance(parsed, dict) else None,
        'combined_roles': parsed.get('combined-roles') if isinstance(parsed, dict) else None,
        'users': parsed.get('users') if isinstance(parsed, dict) else None,
        'raw': parsed,
    }

    module.exit_json(
        changed=False,
        http_status=status,
        identity_info=identity_info,
    )


if __name__ == '__main__':
    main()
