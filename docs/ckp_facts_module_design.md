# `webfargo.check_point.gather_facts` Module Design

## `webfargo.check_point.gather_facts`

A single module that collects all Check Point-specific facts in one call,
returning a structured dict. The module runs on the target host and uses
`module.run_command()` for all CLI interactions.

### Module Interface

```yaml
- name: Gather Check Point facts
  webfargo.check_point.gather_facts:
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
    #   - take
  register: chkp_facts

# Access facts:
#   chkp.facts.sic.name
#   chkp.facts.host_type.is_gateway
#   chkp.facts.host_type.is_management
#   chkp.facts.policy.package
#   chkp.facts.hotfixes.FW1.jhf
#   chkp.facts.vsx
#   chkp.facts.cluster
#   chkp.facts.hardware.platform
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
    # the host is the management server. Playbooks can use
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
  take:
    code_name: "ivory_main"
    take_number: 631

  hardware:
    platform: "dell"         # "dell", "hp", "checkpoint_appliance", "virtual", "unknown"
    model: "PowerEdge R640"  # raw model string from clish output
```

---

### Using the module

```yaml
- hosts: check_point
  gather_facts: false

  tasks:
    - name: Gather Check Point facts
      webfargo.check_point.gather_facts:
      register: chkp

    - debug:
        msg: "JHF: {{ chkp.facts.hotfixes.FW1.jhf }}"

    # Or via ansible_facts (set_ansible_facts: true is default)
    - debug:
        msg: "Policy: {{ ansible_facts.chkp.policy.policy_package }}"
      when: ansible_facts.chkp.host_type.is_gateway
```

### Selective Collection

```yaml
- name: Just check host type and hotfixes
  webfargo.check_point.gather_facts:
    gather_subset:
      - host_type
      - hotfixes
  register: chkp
```

---
