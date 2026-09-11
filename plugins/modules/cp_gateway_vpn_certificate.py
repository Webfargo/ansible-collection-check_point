#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Webfargo Data Security, Inc.
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: cp_gateway_vpn_certificate
short_description: Renew VPN certificates on Check Point gateway or cluster objects
description:
  - Renews a VPN certificate on a Check Point simple-gateway or simple-cluster
    object via the Management API (C(vpn-settings.certificates.renew)).
  - Complements C(check_point.mgmt.cp_mgmt_simple_gateway), which does not
    expose C(vpn-settings.certificates) parameters.
  - Verifies post-renewal that the certificate status is C(signed).
  - C(add) and C(remove) certificate operations (external PKI enrollment) are
    not implemented.
version_added: "1.0.0"
author:
  - Duane Toler (dtoler@webfargo.com)
options:
  name:
    description:
      - Name of the gateway or cluster object in SmartConsole.
    type: str
    required: true
  gateway_type:
    description:
      - Whether the target object is a simple gateway or an HA cluster.
      - Determines whether C(set-simple-gateway) or C(set-simple-cluster) is called.
    type: str
    choices: ['gateway', 'cluster']
    default: gateway
  certificate_name:
    description:
      - Name of the certificate to renew, as it appears in the gateway object.
      - The certificate must already exist; this module does not enroll new certificates.
    type: str
    required: true
  alternate_names:
    description:
      - Subject Alternative Name (SAN) entries for the renewed certificate.
      - Each entry requires C(name_type) and C(value).
      - SANs rarely change; the same values are typically sent on each renewal.
    type: list
    elements: dict
    required: true
    suboptions:
      name_type:
        description:
          - SAN type. Maps to C(name-type) in the API payload.
        type: str
        choices: ['dn', 'email', 'fqdn', 'ip address']
        required: true
      value:
        description:
          - SAN value corresponding to C(name_type).
        type: str
        required: true
  version:
    description:
      - Version of the Check Point Management API to use.
      - If not specified, the latest API version is used.
    type: str
  auto_publish_session:
    description:
      - Whether to publish the Management API session after a successful change.
      - Set to C(false) if batching multiple changes and publishing separately.
    type: bool
    default: true
  wait_for_task:
    description:
      - Whether to wait for asynchronous tasks to complete before returning.
    type: bool
    default: true
  wait_for_task_timeout:
    description:
      - Maximum number of minutes to wait for a task to complete.
    type: int
    default: 30
notes:
  - Requires the C(httpapi) connection plugin with Check Point credentials.
  - Requires R82+ management server for C(vpn-settings) in the API response.
  - If the named certificate does not exist the API will return an error naturally.
  - The C(set-) API response returns the full gateway object; post-renewal
    certificate state is read from that response without a separate facts call.
seealso:
  - module: check_point.mgmt.cp_mgmt_simple_gateway
  - module: check_point.mgmt.cp_mgmt_simple_cluster
  - module: check_point.mgmt.cp_mgmt_simple_gateway_facts
'''

EXAMPLES = r'''
- name: Renew VPN certificate on a simple gateway
  webfargo.check_point.cp_gateway_vpn_certificate:
    name: gw-prod-01
    gateway_type: gateway
    certificate_name: defaultCert
    alternate_names:
      - name_type: fqdn
        value: gw-prod-01.example.com
      - name_type: ip address
        value: 192.0.2.10

- name: Renew VPN certificate on a cluster object
  webfargo.check_point.cp_gateway_vpn_certificate:
    name: cluster-prod-01
    gateway_type: cluster
    certificate_name: defaultCert
    alternate_names:
      - name_type: fqdn
        value: cluster-prod-01.example.com

- name: Renew without auto-publishing (caller publishes later)
  webfargo.check_point.cp_gateway_vpn_certificate:
    name: gw-prod-02
    gateway_type: gateway
    certificate_name: defaultCert
    auto_publish_session: false
    alternate_names:
      - name_type: ip address
        value: 192.0.2.20
'''

RETURN = r'''
changed:
  description: Whether a renewal was performed.
  returned: always
  type: bool
cert_status:
  description: Certificate status after renewal (C(signed) or C(unsigned)).
  returned: always
  type: str
cert_expiration_posix:
  description: >
    Certificate expiration as milliseconds since Unix epoch, from the
    post-renewal API response.
  returned: always
  type: int
cert_expiration_iso8601:
  description: >
    Certificate expiration in ISO 8601 format, from the post-renewal API
    response.
  returned: always
  type: str
cp_response:
  description: >
    Raw JSON response from the Check Point Management API set- call.
    Contains the full gateway/cluster object including updated vpn-settings.
  returned: always
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection
from ansible_collections.check_point.mgmt.plugins.module_utils.checkpoint import (
    send_request,
    get_version,
    parse_fail_message,
    discard_and_fail,
    handle_publish,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_cert(response, certificate_name):
    """Find a certificate by name in the vpn-settings.certificates list."""
    try:
        certs = response.get('vpn-settings', {}).get('certificates', [])
        for cert in certs:
            if cert.get('name') == certificate_name:
                return cert
    except (AttributeError, TypeError):
        pass
    return None


def _build_set_payload(name, certificate_name, alternate_names):
    """Build the set-simple-gateway / set-simple-cluster payload."""
    return {
        'name': name,
        'vpn-settings': {
            'certificates': {
                'renew': {
                    'name': certificate_name,
                    'alternate-names': [
                        {'name-type': entry['name_type'], 'value': entry['value']}
                        for entry in alternate_names
                    ],
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    argument_spec = dict(
        name=dict(type='str', required=True),
        gateway_type=dict(
            type='str',
            choices=['gateway', 'cluster'],
            default='gateway',
        ),
        certificate_name=dict(type='str', required=True),
        alternate_names=dict(
            type='list',
            elements='dict',
            required=True,
            options=dict(
                name_type=dict(
                    type='str',
                    choices=['dn', 'email', 'fqdn', 'ip address'],
                    required=True,
                ),
                value=dict(type='str', required=True),
            ),
        ),
        # Standard check_point.mgmt arguments
        version=dict(type='str'),
        auto_publish_session=dict(type='bool', default=True),
        wait_for_task=dict(type='bool', default=True),
        wait_for_task_timeout=dict(type='int', default=30),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name            = module.params['name']
    gateway_type    = module.params['gateway_type']
    certificate_name       = module.params['certificate_name']
    alternate_names = module.params['alternate_names']

    endpoint_map = {
        'gateway': ('show-simple-gateway', 'set-simple-gateway'),
        'cluster': ('show-simple-cluster', 'set-simple-cluster'),
    }
    show_endpoint, set_endpoint = endpoint_map[gateway_type]

    connection = Connection(module._socket_path)
    version    = get_version(module)

    # ------------------------------------------------------------------
    # Build payload
    # ------------------------------------------------------------------
    set_payload = _build_set_payload(name, certificate_name, alternate_names)

    # ------------------------------------------------------------------
    # check_mode: report what would be sent without making the call
    # ------------------------------------------------------------------
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg="Check mode — would POST to '{}' with payload: {}".format(
                set_endpoint, set_payload
            ),
            cp_response={},
        )

    # ------------------------------------------------------------------
    # Perform renewal
    # ------------------------------------------------------------------
    set_code, set_response = send_request(
        connection, version, set_endpoint, set_payload
    )

    if set_code != 200:
        discard_and_fail(module, set_code, set_response, connection, version)

    # ------------------------------------------------------------------
    # Verify post-renewal certificate state from the set- response
    # ------------------------------------------------------------------
    renewed_cert = _find_cert(set_response, certificate_name)

    if renewed_cert is None:
        module.fail_json(
            msg="Renewal appeared to succeed but certificate '{}' was not found "
                "in the response. Verify the gateway object manually.".format(certificate_name),
            cp_response=set_response,
        )

    cert_status = renewed_cert.get('status')
    if cert_status != 'signed':
        module.fail_json(
            msg="Renewal completed but certificate '{}' status is '{}', expected 'signed'. "
                "Check SmartConsole for details.".format(certificate_name, cert_status),
            cp_response=set_response,
            cert_status=cert_status,
        )

    expiration              = renewed_cert.get('expiration-date', {})
    cert_expiration_posix   = expiration.get('posix')
    cert_expiration_iso8601 = expiration.get('iso-8601')

    # ------------------------------------------------------------------
    # Publish — handle_publish reads auto_publish_session from module.params
    # ------------------------------------------------------------------
    handle_publish(module, connection, version)

    # ------------------------------------------------------------------
    # Return
    # ------------------------------------------------------------------
    module.exit_json(
        changed=True,
        cert_status=cert_status,
        cert_expiration_posix=cert_expiration_posix,
        cert_expiration_iso8601=cert_expiration_iso8601,
        cp_response=set_response,
    )


if __name__ == '__main__':
    main()
