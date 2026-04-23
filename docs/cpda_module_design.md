# Check Point Deployment Agent modules: Design Document

## The da_cli Interface

### Command Categories

**Action commands** — these initiate async operations and return an `Action ID`:
- `add_private_package package=<n>` — download an unpublished package from Check Point's online repo ("Check Point Cloud"); package name must be known
- `download package=<n>` — download a publicly available package from the online repository
- `verify package=<n> [role=<role>]`
- `install package=<n> [reboot_delay=<seconds>]`
- `upgrade package=<n> [reboot_delay=<seconds>]`
- `clean_install package=<n> [role=<machine role>] [reboot_delay=<seconds>]`
- `uninstall package=<n> [reboot_delay=<seconds>] [method=<completely|last_take>]`
- `import package=<n> [location=<location>]` *(location is actually required)*
- `prepare package=<n>`
- `complete package=<n>`
- `delete package=<n>`
- `cancel package=<n>`

**Info/status commands** — most return `Action ID: -1` or `"0"`; some return direct JSON documents:
- `da_status` — returns `Action ID: "0"`; agent state, build number, update progress
- `packages_info [status=<filter>]` — returns JSON document directly (no Action ID); package list with `numberOfPackages` and `packages` array
- `package_info package=<n>` — returns JSON document directly (no Action ID); single package object
- `get_version` — always returns `{"version": "1"}`; use `DABuildNumber` from `da_status` JSON output instead
- `get_status_of_action actionID=<id>` — poll action progress
- `is_pending_reboot` — returns `{"Action ID": "0", "Message": "no reboot"}` (recent addition; untested in older builds)
- `check_for_updates` — returns `Action ID: -1` but is actually **async**; must poll `da_status` `"Update Status"` until `"done"`
- `show_progress [progress_file=<file>]` — reads from a semaphore file written by another process; not useful for automation
- `collect_logs [destination=<path>]`
- `edit_configuration ...`
- `upgrade_tools_update_status`

### JSON Response Patterns

**Initial action command response (immediately after submitting):**
```json
{
  "Action ID": "209",
  "Message": "verify command delivered to service.",
  "Package": "Check_Point_R82_jumbo_hf_main_Bundle_T60_FULL.tgz"
}
```

**Action status response (via `get_status_of_action`):**
```json
{
  "Action ID": "209",
  "Action Type": "Verify",
  "DAService State": "ready",
  "ExtendedMessage": "N/A",
  "Message": "Checking conflicts:",
  "Package": "Check_Point_R82_jumbo_hf_main_Bundle_T60_FULL.tgz",
  "Progress": "70",
  "Status": "in progress"
}
```

**Key quirks:**
- JSON keys use caps and spaces: `"Action ID"`, `"DAService State"`, `"Action Type"`
- `"Action ID"` is a string, not an integer (Check Point's output).  It is
  safely convertible to `int` for arithmetic or comparison.  The value
  `"-1"` is a sentinel meaning "not an action command" — not an error.
- `"Progress"` is a string percentage ("0" through "100"), but can also be
  an **empty string** `""` for some action types (e.g. delete). Code must
  handle this safely.
- `"Status"` values: `"success"`, `"failure"`, `"in progress"`
- `"Message"` can contain embedded JSON as a string (see Verify action below)
- Non-action commands return `"Action ID": "-1"` (or `"0"` for `da_status`)

### da_status Response

The `da_status` command returns the overall agent state:

```json
{
  "Action ID": "0",
  "DABuildNumber": "2672",
  "DAService State": "ready",
  "Installation in Progress": false,
  "Last Update Time": "Wed Feb 11 14:55:28 2026",
  "New DA Availability": "up to date",
  "Update Status": "done"
}
```

**Key fields:**
- `"DAService State"` — `"ready"` means the agent is idle and accepting commands
- `"Installation in Progress"` — boolean (actual boolean, not string)
- `"Update Status"` — `"done"` when idle; during `check_for_updates` this shows
  progress strings like `"Validating candidates 90%"`, `"Processing candidates 97%"`
- `"DABuildNumber"` — the actual DA version; **only present in newer DA builds**.
  Older versions omit this field entirely; use `dbget installer:da_build` as fallback.

### check_for_updates Behavior

**Important:** `check_for_updates` returns `Action ID: -1` (non-action pattern)
but the operation is actually **asynchronous**. The command returns immediately
with a message, and the actual update progress must be monitored via
`da_status` by polling `"Update Status"` until it returns to `"done"`:

```json
{"Action ID": "-1", "Message": "Checking for new available packages..."}
```

Then poll `da_status`:
```
"Update Status": "Validating candidates 90%"  → still working
"Update Status": "Processing candidates 97%"  → still working
"Update Status": "done"                        → complete
```

This means the module utils `check_for_updates` implementation cannot just
fire-and-forget — it must poll `da_status` afterward.

### get_version

`da_cli get_version` always returns a static value:
```json
{"Action ID": "0", "version": "1"}
```

The actual DA build number must be obtained through a fallback chain:
1. `da_status` → `"DABuildNumber"` key (newer DA builds only)
2. `dbget installer:da_build` → returns build number directly (works on all versions)

```bash
# Newer builds: DABuildNumber in da_status output
$ da_cli da_status | jq -r '.DABuildNumber'
2672

# All builds: config database query
$ dbget installer:da_build
2672
```

### Verify Message Structure

When a verify action completes, the `"Message"` field contains stringified JSON
with install/upgrade applicability details.

**Full verify success response (real example, R82 JHF T39):**
```json
{
  "Action ID": "97",
  "Action Type": "Verify",
  "DAService State": "ready",
  "ExtendedMessage": "N/A",
  "Message": "{\"clean-install\":{\"applicable\":false,...},\"install\":{\"applicable\":true,...},...}",
  "Package": "Check_Point_R82_jumbo_hf_main_Bundle_T39_FULL.tgz",
  "Progress": "100",
  "Status": "success"
}
```

**Decoded Message JSON (from the success case above):**

```json
{
  "clean-install": {
    "applicable": false,
    "messages": null,
    "success": false
  },
  "install": {
    "applicable": true,
    "messages": [
      {
        "message-code": "OK",
        "text": "Package is available for installation."
      }
    ],
    "success": true
  },
  "upgrade": {
    "applicable": false,
    "messages": null,
    "success": false
  },
  "warning-install": {
    "applicable": true,
    "messages": null,
    "success": false
  },
  "warning-upgrade": {
    "applicable": false,
    "messages": null,
    "success": false
  }
}
```

**Version upgrade package (R82 Install and Upgrade, real example):**

For version upgrade packages like `Check_Point_R82_T777_Gaia_Install_and_Upgrade.tgz`,
the verify shows `clean-install` and `upgrade` as applicable — NOT `install`:

```json
{
  "clean-install": {
    "applicable": true,
    "messages": [{"message-code": "OK", "text": "Installation is allowed."}],
    "success": true
  },
  "install": {
    "applicable": false,
    "messages": null,
    "success": false
  },
  "upgrade": {
    "applicable": true,
    "messages": [{"message-code": "OK", "text": "Upgrade is allowed."}],
    "success": true
  },
  "warning-install": {
    "applicable": true,
    "messages": null,
    "success": false
  },
  "warning-upgrade": {
    "applicable": true,
    "messages": null,
    "success": false
  }
}
```

**Interpretation:**
- Three operation types exist: `clean-install`, `install`, and `upgrade`
- **Jumbo HFA packages** (patches): `install.applicable` is `true`;
  `clean-install` and `upgrade` are `false`. Use `da_cli install`.
- **Version upgrade packages**: `clean-install.applicable` and/or
  `upgrade.applicable` are `true`; `install.applicable` is typically `false`.
  Use `da_cli upgrade` (or `da_cli clean_install` for fresh installs).
- The distinction between `clean-install` and `upgrade` is up to the admin.
- `install.messages` / `upgrade.messages` — details about eligibility.
  In success cases, `message-code` is `"OK"`. Other message-codes may
  exist but are undocumented. The `"DEPENDENCY"` code specifically
  appears only when verify returns `Status: "failure"` (e.g. package
  already installed — `"Package is already installed and can not be
  re-installed."`), not in successful verify responses.
- `warning-install` / `warning-upgrade` — `applicable` can be `true` even
  when `messages` is `null` (meaning: warnings *could* apply, but there
  aren't any). Only surface warnings when both `applicable` is `true`
  AND `messages` is non-null.
- A verify can return `Status: "failure"` if the package is already installed
  (message-code `"DEPENDENCY"`), which is not necessarily an error condition
  — the module needs to distinguish "already installed" from actual failures.

### Progress 100 Does Not Mean Done

**All action types** (download, verify, install, upgrade) can reach
`Progress: "100"` while `Status` remains `"in progress"`. The polling
logic must **never** treat Progress 100 as completion — always wait for
`Status` to change to `"success"` or `"failure"`.

### Reboot-Imminent Signals

For actions that trigger a reboot (install, uninstall, upgrade), da_cli emits
a specific `"Message"` value at Progress 100 while Status remains `"in progress"`,
just before the reboot fires. This is the reliable signal to treat the action
as complete and return before the SSH connection drops.

**Known reboot-imminent message strings by action type:**

| Action Type | Message value |
|---|---|
| Install | `"Going to reboot:"` |
| Uninstall | `"Uninstallation Complete"` |
| Upgrade | TBD (tested separately) |

The signal persists for approximately 30-90 seconds before the actual reboot,
depending on the `reboot_delay` value set on the da_cli command. **`reboot_delay`
must be set** (30 seconds is the default and recommended) to guarantee at least one poll
cycle captures the message before the host goes down.

Real captured sequence for an install:
```
22:29:42  Progress: 100, Status: "in progress", Message: "Going to reboot:"
22:29:47  Progress: 100, Status: "in progress", Message: "Going to reboot:"
  ... (polling continues for ~90 seconds) ...
22:30:16  Broadcast: "The system is going down for reboot NOW!"
```

### Upgrade Reboot Quirk (Additional)

In addition to the general Progress/Status behavior, upgrade operations
have an additional reboot complication:
1. `Progress` reaches `"100"`, `Status` remains `"in progress"` (normal)
2. `Status` becomes `"success"` or... the system **reboots** (upgrade-specific)
3. During reboot, `da_cli` is unreachable (SSH connection fails)
4. SSH host key may change after reboot (version-dependent)
5. After reboot, same `Action ID` can be polled again
6. `Progress` **drops back** to a lower value (e.g. `"60"`)
7. `Progress` climbs back to `"100"` and `Status` becomes `"success"` or `"failure"`
8. If upgrade failed, the system *may* auto-revert (not guaranteed)

This means the polling logic for upgrades must:
- Handle SSH connection failures gracefully during reboot window
- Potentially handle changed SSH host keys
- Use significantly longer timeouts than install operations

### Package State Strings

The `state` field in package info responses is a freeform human-readable
string to describe the package availability.  Known values observed in
production:

| Condition | `state` value |
|---|---|
| Not yet downloaded | `"Available for download"` |
| Downloaded, not installed | `"Available for Install"` |
| Installed | `"Installed Successfully"` |

Use `isInRepository` (boolean) for reliable download status checks.  For
installed status, normalize the `state` string before comparing — the module
uses `state.lower().startswith("installed")` to handle case variation.

### Package Info Structure

```json
{
  "numberOfPackages": 15,
  "packages": [
    {
      "availableFrom": "2025-11-18 00:00:00",
      "blocksUninstall": false,
      "broughtVersion": "6.0_5_4",
      "build": 120,
      "category": "jumbo",
      "children": "Check_Point_R81_20_jumbo_hf_main_Bundle_T115_FULL.tgz",
      "description": "<p>R81.20 Jumbo Hotfix Accumulator...</p>",
      "displayName": "R81.20 Jumbo Hotfix Accumulator Recommended Jumbo Take 120",
      "fileSize": "3219985395",
      "filename": "Check_Point_R81_20_jumbo_hf_main_Bundle_T120_FULL.tgz",
      "hasMetadata": true,
      "htmlReportExists": false,
      "installCritical": false,
      "isBlinkImage": false,
      "isHfa": false,
      "isInRepository": false,
      "isUpgradeAllowed": false,
      "md5": "229fef4d3ecfdf10125ee8ccb6d1ff38",
      "order": 0,
      "packageKey": "CheckPoint#CPUpdates#All#6.0#5#4#BUNDLE_R81_20_JUMBO_HF_MAIN#120",
      "packageOrigin": "Download Center",
      "packageType": "Wrapper",
      "parents": "Check_Point_R81_20_jumbo_hf_main_Bundle_T122_FULL.tgz",
      "product": "CPUpdates",
      "requiresReboot": true,
      "state": "Available for download",
      "tag": {
        "importance": "latest"
      },
      "version": "6.0"
    }
  ]
}
```

**Key fields:**
- `tag.importance == "latest"` — identifies the most recent version of a
  package type. This is the primary field used for auto-detection. Present
  on both Jumbo HFA and major version packages.
- `category` — package classification:
  - `"jumbo"` — Jumbo HFA packages (any version, not just latest)
  - `"major"` — full version upgrade packages (e.g. R82 Install and Upgrade)
  - `"misc"` — miscellaneous packages (custom hotfixes, auto-installed tools)
- `state` — human-readable status string.  See Package State Strings section
  above.  Not widely used for programmatic checks.
- `isInRepository` — `false` when the package is known but not yet downloaded;
  becomes `true` after download completes. This is the reliable boolean for
  checking download status.
- `requiresReboot` — whether installation triggers a reboot
- `children` / `parents` — package dependency chain between takes
- `packageType` — e.g. `"Wrapper"` for Jumbo bundles, `"Major Version"` for upgrades
- `product` — e.g. `"CPUpdates"` for Jumbos, `"Major"` for version upgrades
- **`isHfa`** — Despite the name, this is `false` even on actual Jumbo HFA
  packages.  Do not use for identification.  Use `tag.importance` and/or
  `category` instead.
- Installed packages have additional keys: `installedOn`, `downloadedOn`,
  `installLogFile`, `build`

**Major version upgrade package example (R82):**

```json
{
  "availableFrom": "2024-10-20 00:00:00",
  "blocksUninstall": false,
  "broughtVersion": "6.0_5_5",
  "category": "major",
  "description": "R82 Gaia Clean Install and Upgrade...",
  "displayName": "R82 Gaia Clean Install and upgrade",
  "fileSize": "5218750374",
  "filename": "Check_Point_R82_T777_Gaia_Install_and_Upgrade.tgz",
  "isBlinkImage": false,
  "isInRepository": false,
  "packageKey": "CheckPoint#Major#All#6.0#5#5#R82_jaguar_opt_main_T777",
  "packageOrigin": "Download Center",
  "packageType": "Major Version",
  "product": "Major",
  "requiresReboot": true,
  "state": "Available for download",
  "tag": { "importance": "latest" },
  "version": "6.0"
}
```

Note that both Jumbo HFA and major version packages can have
`tag.importance == "latest"`. The `category` field distinguishes them.

Check Point uses two Jumbo HFA release trains:
- **Recommended** — stable, production-ready. Identified by `category == "jumbo"`
  AND `tag.importance == "latest"` AND not yet installed (`installedOn` absent).
  Despite the naming, `tag.importance == "latest"` means "Recommended".
- **Latest** — next candidate release.  Identified by `category == "jumbo"`
  AND no `tag.importance` set AND not yet installed.  Not always available. 
  If multiple candidates exist, select highest `build`.

The `find_recommended_jumbo()` and `find_latest_jumbo()` helpers implement
these filters. The `da_package_info` module exposes them via the
`jumbo` parameter (`jumbo: recommended` or `jumbo: latest`). A separate
`category` parameter provides simple type filtering across all three
package categories (`jumbo`, `major`, `misc`).

### Typical Jumbo HFA Workflow

This is the most common operation — installing a Jumbo HotFix Accumulator:

```
1. check_for_updates              → sync local repo with Check Point servers
2. packages_info                  → find available packages, identify latest
3. packages_info | .isInRepository → check if already downloaded
4. download package=<n>           → download if needed (Action ID returned)
5. get_status_of_action           → poll until download complete (Progress 100, success)
6. verify package=<n>             → pre-install verification (Action ID returned)
7. get_status_of_action           → poll until verify complete
8.   └── parse Message JSON       → check install.applicable, read warnings
9. install package=<n>            → install the package (Action ID returned)
10. get_status_of_action          → poll until "Going to reboot:" message detected
11. (module returns success; host reboots after reboot_delay seconds)
12. Wait for host to come back up
```

**Real example from uploaded sequence (R81.20 JHF T84):**
```
Action 114: Add_Private_Package → success
Action 115: Download            → success
Action 116: Verify              → success (install.applicable=true, "OK")
Action 117: Install             → success (Progress 100)
```

**Real example from R82 JHF T60 (already installed):**
```
Action 209: Verify → failure
  Message JSON: install.applicable=true BUT
    message-code="DEPENDENCY", "Package is already installed"
```
This verify "failure" is actually an idempotency signal — the module
must recognize this as "already installed, no action needed."

### Upgrade Workflow (Version Upgrades)

```
1-8.  Same as above through verify
9.    upgrade package=<n>          → begin upgrade (Action ID returned)
10.   get_status_of_action         → poll; Progress climbs to 100
11.   Status REMAINS "in progress" at Progress 100 ← THE QUIRK
12.   System reboots (SSH drops, da_cli unreachable)
13.   SSH host key may have changed
14.   After reboot, same Action ID can be polled
15.   Progress DROPS BACK to lower value (e.g. 60)
16.   Progress climbs back to 100
17.   Status finally becomes "success" or "failure"
18.   If failure, system MAY auto-revert (not guaranteed)
```

**Private/custom package workflow:**
```
1. (copy file to host)
2. import package=<file> location=<dir>   → import into local repo
3. get_status_of_action                   → poll until import complete
4. verify → install (same as above)
```

**Note on `import`:** Despite the da_cli help suggesting `location=` is optional,
it is actually **mandatory** and must be the directory path where the package
file was placed (directory only, not full file path).


---

## Module Architecture

### Collection Structure

```
ansible-collection-check_point/
├── galaxy.yml
├── README.md
└── plugins/
    ├── module_utils/
    │   └── da_cli.py                  # Shared CLI execution & JSON handling
    └── modules/
        ├── da_status.py           # da_status, build number, is_pending_reboot
        ├── da_package_info.py     # packages_info, package_info
        ├── da_package.py          # download/import/verify/install/uninstall/delete
        └── da_command.py          # Low-level: run arbitrary da_cli commands
```

### Module Utils: `da_cli.py`

The core shared library — all modules import `DaCliClient` and `DaCliError`
from here.  Handles CLI execution, JSON parsing (including key normalization
and embedded-JSON-in-Message), action polling, and all da_cli behavioral
quirks.

**Key responsibilities:**
- `run()` — execute any da_cli subcommand, parse JSON, normalize keys
- `poll_action()` — poll `get_status_of_action` until completion; handles
  Progress/Status quirks, reboot-imminent detection, and upgrade SSH-drop
  recovery
- `run_action()` — convenience wrapper combining `run()` + `poll_action()`
- `check_for_updates()` — fires the command and polls `da_status` until
  Update Status returns to `"done"`
- `find_recommended_jumbo()` / `find_latest_jumbo()` — package
  auto-detection helpers
- `_is_reboot_imminent()` — detects reboot-imminent message strings by
  action type

### Module: `da_status`

Read-only module for agent status, build number, and reboot state.

**Returns:** `da_status` (raw dict), `build_number`, `service_state`, `ready` (bool),
`pending_reboot` (bool or None on older builds), `installation_in_progress`, `update_status`

**Options:** `wait_for_ready` (bool) — poll until DA is idle before returning.
`timeout` (int, default 120).

### Module: `da_package_info`

Read-only module for querying the package catalog.

**Query modes (mutually exclusive):**
- `name` — single package by filename
- `jumbo: recommended|latest` — auto-detect Jumbo HFA by release train
- `category: jumbo|major|misc` — filter all packages by category
- default — list packages with optional `status` filter

**Returns:** `package` (dict) or `packages` (list), `found` (bool), `count` (int)

### Module: `da_package`

The main workhorse — all state-changing package operations with built-in polling
and idempotency.

**States:**
- `downloaded` — ensure package is in local repository (idempotent via `isInRepository`)
- `private_download` — download unpublished package via `add_private_package`
- `imported` — import a file already on the host filesystem (requires `location`)
- `verified` — run pre-install verification; returns `verify_details`; never sets `changed`
- `installed` — download + verify + install; idempotent via normalized package state
- `upgraded` — verify + upgrade; handles reboot-during-progress quirk via `is_upgrade=True`
- `absent` — uninstall if installed, delete from repo if downloaded, no-op if not present

**Key options:**
- `reboot_delay` (int, default 30) — **required for reboot operations**; creates the
  polling window where reboot-imminent signals are visible before the host goes down
- `verify_before_install` (bool, default true) — auto-verify before install/upgrade
- `refresh` (bool) — run `check_for_updates` before the operation
- `poll_interval` (int, default 15) / `timeout` (int, default 900)

### Module: `da_command`

Low-level escape hatch for any `da_cli` subcommand not covered by the other modules.

**Options:** `command` (required), `wait` (bool, default true — poll if action command),
`parse_message` (bool), `changed` (bool, default null — override changed detection),
`poll_interval`, `timeout`

**Note:** `check_for_updates` via `da_command` will NOT poll correctly — it returns
Action ID `-1` and `run_action()` returns immediately for non-action commands.
Use `da_package` with `refresh: true` or `da_status` to monitor update completion.

---

## Playbook

```yaml
- name: Install latest Jumbo HFA
  hosts: firewalls
  gather_facts: false

  tasks:
    - name: Install Recommended Jumbo HFA
      webfargo.check_point.da_package:
        state: installed
        refresh: true
        timeout: 1800
      register: install_result

    - name: Show result
      debug:
        var: install_result
```

Or for a more controlled, step-by-step workflow:

```yaml
- name: Jumbo HFA installation workflow
  hosts: firewalls
  gather_facts: false

  tasks:
    - name: Find Recommended Jumbo HFA
      webfargo.check_point.da_package_info:
        jumbo: recommended
        refresh: true
      register: jumbo

    - name: Fail if no Jumbo found
      fail:
        msg: "No Recommended Jumbo HFA available"
      when: not jumbo.found

    - name: Show what we'll install
      debug:
        msg: "Installing {{ jumbo.package.displayName }} ({{ jumbo.package.filename }})"

    - name: Download package
      webfargo.check_point.da_package:
        name: "{{ jumbo.package.filename }}"
        state: downloaded

    - name: Verify package
      webfargo.check_point.da_package:
        name: "{{ jumbo.package.filename }}"
        state: verified
      register: verify

    - name: Show verify details
      debug:
        var: verify.verify_details

    - name: Install package
      webfargo.check_point.da_package:
        name: "{{ jumbo.package.filename }}"
        state: installed
        verify_before_install: false  # already verified above
      register: install_result

    - name: Wait for host to come back after reboot
      when: install_result.changed
      block:
        - name: Wait for SSH to go down
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 90
            sleep: 10
            timeout: 600
      rescue:
        - name: Wait for SSH to come back (rescue)
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 10
            sleep: 10
            timeout: 600

    - name: Check DA status post-install
      webfargo.check_point.da_status:
      register: post_status
```

### Private/Custom Package Workflow

```yaml
- name: Install private hotfix
  hosts: firewalls
  gather_facts: false

  vars:
    hotfix_file: "custom_hotfix_HF999.tgz"
    hotfix_src: "/opt/files/hotfixes/{{ hotfix_file }}"

  tasks:
    - name: Copy hotfix to host
      ansible.builtin.copy:
        src: "{{ hotfix_src }}"
        dest: "/var/log/{{ hotfix_file }}"

    - name: Import into DA repository
      webfargo.check_point.da_package:
        name: "{{ hotfix_file }}"
        state: imported
        location: /var/log

    - name: Verify and install
      webfargo.check_point.da_package:
        name: "{{ hotfix_file }}"
        state: installed
        timeout: 1200
      register: install_result

    - name: Wait for host to come back after reboot
      when: install_result.changed
      block:
        - name: Wait for SSH to go down
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 90
            sleep: 10
            timeout: 600
      rescue:
        - name: Wait for SSH to come back (rescue)
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 10
            sleep: 10
            timeout: 600
```

### Jumbo HFA Install with Reboot Handling

The `da_package` module detects the reboot-imminent signal (`"Going to reboot:"` in
the Message field at Progress 100) and returns a clean result before the host goes
down. **`reboot_delay` must be set** (default 30 seconds) to guarantee the signal
is visible during polling.

After the module returns, use `wait_for_connection` to handle the reboot window.
Do NOT use `ansible.builtin.reboot` — the host is already rebooting and Ansible
does not need to trigger it.

```yaml
    - name: Install latest Jumbo HFA
      webfargo.check_point.da_package:
        state: installed
        refresh: true
        timeout: 1800
      register: install_result

    - name: Wait for host to come back after reboot
      when: install_result.changed
      block:
        - name: Wait for SSH connection to recover
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 90
            sleep: 10
            timeout: 600
      rescue:
        - name: Wait for SSH to come back (rescue path)
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 10
            sleep: 10
            timeout: 600
```

The `rescue` block handles the case where the host is already down when
`wait_for_connection` starts — it retries with a shorter initial delay.

**Do not use `delegate_to: localhost`** for the wait tasks. Ansible must execute
them in the context of the target host's connection so it uses the correct
addressing and credentials.

### Version Upgrade Workflow

Upgrades are the most complex operation due to the reboot-during-progress
behavior. The module handles polling through the reboot via `is_upgrade=True`,
but use generous timeouts and handle potential SSH key changes:

```yaml
- name: Upgrade Check Point version
  hosts: firewalls
  gather_facts: false

  vars:
    upgrade_package: "Check_Point_R82_Upgrade_Package.tgz"

  tasks:
    - name: Copy upgrade package
      ansible.builtin.copy:
        src: "/opt/ansible_shared/files/upgrades/{{ upgrade_package }}"
        dest: "/var/tmp/{{ upgrade_package }}"

    - name: Import upgrade package
      webfargo.check_point.da_package:
        name: "{{ upgrade_package }}"
        state: imported
        location: /var/tmp

    - name: Verify upgrade eligibility
      webfargo.check_point.da_package:
        name: "{{ upgrade_package }}"
        state: verified
      register: verify

    - name: Show upgrade warnings
      ansible.builtin.debug:
        var: verify.warnings
      when: verify.warnings is defined

    - name: Confirm upgrade
      ansible.builtin.pause:
        prompt: "Proceed with upgrade? (Ctrl+C to abort)"

    - name: Execute upgrade
      webfargo.check_point.da_package:
        name: "{{ upgrade_package }}"
        state: upgraded
        verify_before_install: false  # already verified
        timeout: 3600  # upgrades can take a very long time
      register: upgrade_result

    - name: Wait for host to come back after upgrade reboot
      when: upgrade_result.changed
      block:
        - name: Wait for SSH connection to recover
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 90
            sleep: 10
            timeout: 900
      rescue:
        - name: Wait for SSH to come back (rescue path)
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 10
            sleep: 10
            timeout: 900

    # SSH host key may have changed after upgrade
    - name: Remove stale SSH host key
      ansible.builtin.known_hosts:
        name: "{{ ansible_host }}"
        state: absent
      delegate_to: localhost

    - name: Verify post-upgrade status
      webfargo.check_point.da_status:
      register: post_upgrade
```

---

## Known Limitations & Edge Cases

**DA build version compatibility:** Not all hosts run the same DA build
version, and certain packages require a minimum DA build to import or
install.  If a package is incompatible with the host's DA version, it may
fail to import or may simply not appear in `packages_info` results at all. 
There is no reliable programmatic way to check compatibility — it may be
logged, but the log format isn't stable enough to parse.  The modules do not
attempt to detect or handle this; if you hit it, the action will fail with
whatever error `da_cli` returns and the module will surface that message.

**`show_progress`:** Reads from a semaphore file written by another process. 
Not useful for automation; `get_status_of_action` is the correct polling
mechanism.

**`get_version`:** Always returns `{"version": "1"}`.  Use
`get_build_number()` which falls back through `da_status` → `dbget`.

**`is_pending_reboot`:** Recent addition to `da_cli`. May not exist on older
DA builds. The `da_status` module handles this gracefully (returns `None`
if unavailable).

**`DABuildNumber` in `da_status`:** Also a newer addition. Not present in
older DA builds. The `get_build_number()` method falls back to
`dbget installer:da_build`.

**Package state strings are freeform:** The `state` field in package info
responses is not a stable enum. Known values include `"Available for download"`,
`"Available for Install"`, and `"Installed Successfully"`. Always normalize
before comparing — never do a direct string equality check against `state`.
Use `isInRepository` for download status and `state.lower().startswith("installed")`
for install status.

**Reboot-imminent message strings vary by action type:** `"Going to reboot:"`
is emitted by install, `"Uninstallation Complete"` by uninstall. The upgrade
reboot signal is TBD. The `_is_reboot_imminent()` helper in `da_cli.py` is
the single place to add new trigger strings as they are discovered.

**`reboot_delay` is effectively required for reboot operations:** Without it,
the host may reboot before the module receives a clean result. The default
is 30 seconds. Lower values may work but reduce the polling window for
reboot-imminent signal detection.

**Upgrade reboot behavior:** Status stays `"in progress"` at Progress 100,
host reboots, SSH may drop, host key may change, Progress resets and climbs
again. This is confirmed by Check Point TAC as intentional behavior.

**Verify "failure" for installed packages:** A verify returning
`Status: "failure"` with `message-code: "DEPENDENCY"` means the package is
already installed — this is an idempotency signal, not an actual error.

**`wait_for_connection` vs `wait_for` for reboot handling:** Use
`ansible.builtin.wait_for_connection` — not `ansible.builtin.wait_for` with
`delegate_to: localhost`.  The latter runs on the Ansible controller and
does not target the host.  `wait_for_connection` executes in the context of
the target host's connection, using the same addressing and credentials as
all other tasks.
