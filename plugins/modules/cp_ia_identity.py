#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Webfargo Data Security, Inc.
# GNU General Public License v3.0+ (see https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: cp_ia_identity
short_description: Add or delete Check Point Identity Awareness associations via the Identity Web API
version_added: "1.0.0"
description:
  - Talks directly to a Check Point Security Gateway's Identity Awareness Web API
    (C(_IA_API)) to create (C(add-identity)) or revoke (C(delete-identity)) an
    identity association. There is no session login/logout with this API -
    every call is authenticated with a pre-shared secret configured on the
    gateway object in SmartConsole.
  - I(state=present) always reports C(changed=true) on a successful call
    (outside of check mode).  C(delete-identity) does report how many
    associations it actually removed, so I(state=absent) reports
    C(changed=false) when nothing matched I(ip_address) (or the given
    range/subnet) rather than claiming a change that didn't happen.  Use the
    M(cp_ia_identity_info) module if you need to inspect current state
    before deciding whether to call this module at all.
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
  state:
    description:
      - C(present) calls C(add-identity) to create/refresh an association.
      - C(absent) calls C(delete-identity) to revoke one or more associations.
    type: str
    choices: [present, absent]
    default: present
  ip_address:
    description:
      - The association IP address (IPv4 or IPv6, not both).
      - Required when I(state=present). For I(state=absent) this is optional
        if I(subnet) or I(ip_address_first)/I(ip_address_last) is supplied
        instead, but at least one of the four must be given.
    type: str
  user:
    description:
      - Username to associate with I(ip_address). Only used when I(state=present).
      - At least one of I(user) or I(machine) is required when I(state=present).
    type: str
  machine:
    description:
      - Computer/machine name to associate with I(ip_address). Only used when
        I(state=present).
      - At least one of I(user) or I(machine) is required when I(state=present).
    type: str
  domain:
    description:
      - Domain name for I(user)/I(machine). Best practice is to always supply
        this when available, since it disambiguates identical usernames across
        domains. Only used when I(state=present).
    type: str
  user_groups:
    description:
      - List of group names the user belongs to. Only used when I(state=present).
    type: list
    elements: str
  machine_groups:
    description:
      - List of group names the machine belongs to. Only used when I(state=present).
    type: list
    elements: str
  session_timeout:
    description:
      - Session timeout in seconds for this association. Only used when
        I(state=present).
    type: int
  fetch_user_groups:
    description:
      - Whether the gateway should fetch the user's groups itself from the
        user directories defined in SmartConsole, rather than relying on
        I(user_groups). Requires I(calculate_roles=true) or the request will
        fail. Only used when I(state=present).
      - Check Point's own API default for this parameter is C(true) - set it
        to C(false) explicitly if you intend to supply I(user_groups) yourself.
    type: bool
    default: true
  fetch_machine_groups:
    description:
      - Whether the gateway should fetch the machine's groups itself from the
        user directories defined in SmartConsole, rather than relying on
        I(machine_groups). Requires I(calculate_roles=true) or the request
        will fail. Only used when I(state=present).
      - Check Point's own API default for this parameter is C(true) - set it
        to C(false) explicitly if you intend to supply I(machine_groups)
        yourself.
    type: bool
    default: true
  calculate_roles:
    description:
      - Whether the gateway should calculate Access Roles for this association.
        Must be C(true) if either I(fetch_user_groups) or
        I(fetch_machine_groups) is C(true). Only used when I(state=present).
    type: bool
    default: true
  roles:
    description:
      - List of Access Roles to assign directly to this identity, for use when
        I(calculate_roles=false) (i.e. the gateway is not calculating roles
        itself). Only used when I(state=present).
    type: list
    elements: str
  identity_source:
    description:
      - Free-text label identifying the source system feeding this identity
        (for example a NAC product name). Only used when I(state=present).
    type: str
  machine_os:
    description:
      - Operating system of the associated machine, if known. Only used when
        I(state=present).
    type: str
  host_type:
    description:
      - Host type of the associated machine, if known. Only used when
        I(state=present).
    type: str
  client_type:
    description:
      - Restricts a revocation to associations created by a specific identity
        source. Check Point's own API default is empty/C(Any) (delete
        associations from every source); this module defaults to C(ida-api)
        instead so that, out of the box, it only touches associations this
        module itself is likely to have created. Set it to C(Any) explicitly
        to match the gateway's native default and delete regardless of source.
        Only used when I(state=absent).
    type: str
    choices:
      - Any
      - captive-portal
      - ida-agent
      - vpn
      - ad-query
      - multihost-agent
      - radius
      - ida-api
      - identity-collector
    default: ida-api
  revoke_method:
    description:
      - Selects how matching associations are found for deletion. Leave unset
        (or C(null)) to delete a single association by I(ip_address). Set to
        C(mask) to delete every association in I(subnet)/I(subnet_mask). Set
        to C(range) to delete every association between I(ip_address_first)
        and I(ip_address_last). Only used when I(state=absent).
    type: str
    choices: [mask, range]
  subnet:
    description:
      - Subnet to revoke every association in. Required when
        I(revoke_method=mask). Only used when I(state=absent).
    type: str
  subnet_mask:
    description:
      - Mask to use with I(subnet). Required when I(revoke_method=mask). Only
        used when I(state=absent).
    type: str
  ip_address_first:
    description:
      - Start of an IP range to revoke. Required when I(revoke_method=range).
        Only used when I(state=absent).
    type: str
  ip_address_last:
    description:
      - End of an IP range to revoke. Required when I(revoke_method=range).
        Only used when I(state=absent).
    type: str
author:
  - Duane Toler <dtoler@webfargo.com>
'''

EXAMPLES = r'''
- name: Add an identity association
  webfargo.check_point.cp_ia_identity:
    ia_host: "{{ ia_mgmt_host }}"
    shared_secret: "{{ identity_api_secret }}"
    ip_address: "10.10.5.23"
    user: "jdoe"
    domain: "corp.example.com"
    user_groups:
      - "vpn-users"
    fetch_user_groups: false
    calculate_roles: true
    identity_source: "{{ inventory_hostname }}"
    state: present

- name: Revoke a single association
  webfargo.check_point.cp_ia_identity:
    ia_host: "{{ ia_mgmt_host }}"
    shared_secret: "{{ identity_api_secret }}"
    ip_address: "10.10.5.23"
    state: absent

- name: Revoke every association in a subnet
  webfargo.check_point.cp_ia_identity:
    ia_host: "{{ ia_mgmt_host }}"
    shared_secret: "{{ identity_api_secret }}"
    revoke_method: mask
    subnet: "10.10.5.0"
    subnet_mask: "255.255.255.0"
    state: absent

- name: Revoke every association in an IP range, regardless of source
  webfargo.check_point.cp_ia_identity:
    ia_host: "{{ ia_mgmt_host }}"
    shared_secret: "{{ identity_api_secret }}"
    revoke_method: range
    ip_address_first: "10.10.5.1"
    ip_address_last: "10.10.5.50"
    client_type: Any
    state: absent
'''

RETURN = r'''
msg:
  description: Message returned by the gateway, or a local status message.
  type: str
  returned: always
http_status:
  description: HTTP status code returned by the gateway.
  type: int
  returned: when the API call was attempted
count:
  description:
    - Number of identities deleted, as reported by the gateway. Only meaningful for state=absent.
    - When this is present and parses as an integer, it directly determines C(changed) for state=absent (a count of 0 means changed=false).
  type: int
  returned: when state=absent and the call succeeded
response:
  description:
    - Full JSON response body from the gateway, when it could be parsed.
    - On success this may include C(ipv4-address)/C(ipv6-address), C(message),
      and, for I(state=absent), C(count).
    - On failure (HTTP 404/500) the gateway instead returns C(message),
      C(warnings), and an error C(code) such as C(GENERIC_ERROR),
      C(GENERIC_ERR_INVALID_SYNTAX), C(GENERIC_ERR_INVALID_PARAMETER_NAME),
      C(GENERIC_ERR_INVALID_PARAMETER), or
      C(GENERIC_ERR_MISSING_REQUIRED_PARAMETERS).
  type: dict
  returned: when the API call was attempted and the body was valid JSON
'''

import json

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import fetch_url


def build_add_body(module):
    p = module.params
    body = {
        'shared-secret': p['shared_secret'],
        'ip-address': p['ip_address'],
        'user': p['user'],
        'machine': p['machine'],
        'domain': p['domain'],
        'user-groups': p['user_groups'],
        'machine-groups': p['machine_groups'],
        'session-timeout': p['session_timeout'],
        'fetch-user-groups': int(bool(p['fetch_user_groups'])),
        'fetch-machine-groups': int(bool(p['fetch_machine_groups'])),
        'calculate-roles': int(bool(p['calculate_roles'])),
        'roles': p['roles'],
        'identity-source': p['identity_source'],
        'machine-os': p['machine_os'],
        'host-type': p['host_type'],
    }
    return {k: v for k, v in body.items() if v is not None}


def build_delete_body(module):
    p = module.params
    body = {
        'shared-secret': p['shared_secret'],
        'client-type': p['client_type'],
        'ip-address': p['ip_address'],
        'revoke-method': p['revoke_method'],
        'subnet': p['subnet'],
        'subnet-mask': p['subnet_mask'],
        'ip-address-first': p['ip_address_first'],
        'ip-address-last': p['ip_address_last'],
    }
    return {k: v for k, v in body.items() if v is not None}


def call_api(module, endpoint, body):
    url = "https://{0}:{1}/_IA_API/v1.0/{2}".format(
        module.params['ia_host'], module.params['ia_port'], endpoint
    )
    headers = {'Content-Type': 'application/json'}
    response, info = fetch_url(
        module,
        url,
        data=json.dumps(body),
        method='POST',
        headers=headers,
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
            fail_msg = "Identity API call to {0} failed with HTTP {1}: {2}".format(
                endpoint, status, parsed.get('message', info.get('msg'))
            )
            module.fail_json(
                msg=fail_msg,
                http_status=status,
                response=parsed,
                code=parsed.get('code'),
                warnings_from_gateway=parsed.get('warnings'),
            )
        module.fail_json(
            msg="Identity API call to {0} failed with HTTP {1}: {2}".format(
                endpoint, status, info.get('msg', raw)
            ),
            http_status=status,
            response=parsed,
        )

    return status, parsed


def main():
    argument_spec = dict(
        ia_host=dict(type='str', required=True),
        ia_port=dict(type='int', default=443),
        shared_secret=dict(type='str', required=True, no_log=True),
        validate_certs=dict(type='bool', default=False),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        ip_address=dict(type='str'),
        user=dict(type='str'),
        machine=dict(type='str'),
        domain=dict(type='str'),
        user_groups=dict(type='list', elements='str'),
        machine_groups=dict(type='list', elements='str'),
        session_timeout=dict(type='int'),
        fetch_user_groups=dict(type='bool', default=True),
        fetch_machine_groups=dict(type='bool', default=True),
        calculate_roles=dict(type='bool', default=True),
        roles=dict(type='list', elements='str'),
        identity_source=dict(type='str'),
        machine_os=dict(type='str'),
        host_type=dict(type='str'),
        client_type=dict(
            type='str',
            default='ida-api',
            choices=[
                'Any', 'captive-portal', 'ida-agent', 'vpn', 'ad-query',
                'multihost-agent', 'radius', 'ida-api', 'identity-collector',
            ],
        ),
        revoke_method=dict(type='str', choices=['mask', 'range']),
        subnet=dict(type='str'),
        subnet_mask=dict(type='str'),
        ip_address_first=dict(type='str'),
        ip_address_last=dict(type='str'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    state = module.params['state']

    if state == 'present':
        if not module.params['ip_address']:
            module.fail_json(msg="ip_address is required when state=present")
        if not module.params['user'] and not module.params['machine']:
            module.fail_json(msg="at least one of 'user' or 'machine' is required when state=present")
        if (module.params['fetch_user_groups'] or module.params['fetch_machine_groups']) \
                and not module.params['calculate_roles']:
            module.fail_json(msg="calculate_roles must be true when fetch_user_groups or fetch_machine_groups is true")
        body = build_add_body(module)
        endpoint = 'add-identity'
    else:
        revoke_method = module.params['revoke_method']
        if revoke_method is None:
            if not module.params['ip_address']:
                module.fail_json(
                    msg="state=absent with no revoke_method deletes a single association and requires 'ip_address'"
                )
        elif revoke_method == 'mask':
            if not module.params['subnet'] or not module.params['subnet_mask']:
                module.fail_json(msg="revoke_method=mask requires both 'subnet' and 'subnet_mask'")
        elif revoke_method == 'range':
            if not module.params['ip_address_first'] or not module.params['ip_address_last']:
                module.fail_json(msg="revoke_method=range requires both 'ip_address_first' and 'ip_address_last'")
        body = build_delete_body(module)
        endpoint = 'delete-identity'

    if module.check_mode:
        module.exit_json(changed=True, msg="check mode: {0} not called".format(endpoint))

    status, parsed = call_api(module, endpoint, body)

    msg = parsed.get('message') if isinstance(parsed, dict) else None
    count = None
    if isinstance(parsed, dict) and 'count' in parsed:
        try:
            count = int(parsed['count'])
        except (TypeError, ValueError):
            count = parsed['count']

    if endpoint == 'delete-identity':
        # delete-identity is the one call where the gateway tells us whether
        # it actually removed anything (via 'count'). If nothing matched,
        # report changed=False instead of blindly claiming success changed
        # something. If 'count' couldn't be parsed as an int, fall back to
        # changed=True - we can't prove nothing happened, so don't claim
        # idempotency we can't back up.
        changed = (count != 0) if isinstance(count, int) else True
    else:
        # add-identity has no equivalent signal - the gateway doesn't say
        # whether this created a new association or refreshed an identical
        # existing one, so we can't claim idempotency here.
        changed = True

    result = dict(
        changed=changed,
        msg=msg or "{0} call succeeded".format(endpoint),
        http_status=status,
        response=parsed,
    )
    if count is not None:
        result['count'] = count
    module.exit_json(**result)


if __name__ == '__main__':
    main()
