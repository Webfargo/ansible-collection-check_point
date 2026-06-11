# Check Point Deployment Agent modules: Design Document

## The da_cli Interface

### Command Categories

**Action commands** — these initiate async operations and return an `Action ID`:
- `add_private_package package=<n>` — download an unpublished package from Check Point's online repo ("Check Point Cloud"); package name must be known
- `download package=<n>` — download a publicly available package from the online repository
- `verify package=<n> [role=<role>]`
- `verify_uninstall package=<n>` — check whether a package can be safely uninstalled; returns eligibility message
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
- `"Action ID"` is a string, not an integer (Check Point's output). It is
  safely convertible to `int` for arithmetic or comparison. The value
  `"-1"` is a sentinel meaning "not an action command" — not an error.
- `"Progress"` is a string percentage ("0" through "100"), but can also be
  an **empty string** `""` for some action types (e.g. delete, and during
  reboot transitions). Code must handle this safely.
- `"Status"` values: `"success"`, `"failure"`, `"in progress"`, `"interrupted"`
- `"Message"` can contain embedded JSON as a string (see Verify action below)
- Non-action commands return `"Action ID": "-1"` (or `"0"` for `da_status`)
- `"DAService State"` reflects the DA service state and transitions to `"down"`
  during reboot for uninstall and upgrade operations

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
  progress strings like `"Validating candidates 90%"`, `"Processing candidates 97%"`;
  `"not allowed"` on hosts without Check Point Cloud access (treated as ready)
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
"Update Status": "not allowed"                 → host has no CP Cloud access; treat as done
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
  AND `messages` is non-null. Warning text may contain `(N warnings) \n •`
  formatting from Check Point's own rendering.
- A verify can return `Status: "failure"` if the package is already installed
  (message-code `"DEPENDENCY"`), which is not necessarily an error condition
  — the module needs to distinguish "already installed" from actual failures.

### verify_uninstall Message Structure

`verify_uninstall` returns a plain string in the `"Message"` field (not embedded JSON):

```json
{
  "Action ID": "113",
  "Action Type": "Verify_Uninstall",
  "DAService State": "ready",
  "Message": "This package can be uninstalled.",
  "Progress": "100",
  "Status": "success"
}
```

Known `verify_uninstall` outcomes:

| Status | Message | Meaning |
|---|---|---|
| `success` | `"This package can be uninstalled."` | Safe to uninstall |
| `success` | `"This package is not installed."` | Package not present |
| `failure` | `"A newer version is installed on top of..."` | Dependency block — uninstall newer take first |

### Progress 100 Does Not Mean Done

**All action types** (download, verify, install, upgrade) can reach
`Progress: "100"` while `Status` remains `"in progress"`. The polling
logic must **never** treat Progress 100 as completion — always wait for
`Status` to change to `"success"` or `"failure"`.

### Reboot-Imminent Signals

For actions that trigger a reboot (install, uninstall, upgrade), da_cli provides
observable signals before or at the reboot moment. The detection method varies
by action type.

**Install** — `"Going to reboot:"` appears in the `Message` field at Progress 100
while Status remains `"in progress"`. This signal persists for 30-90 seconds
before the actual reboot. `DAService State` stays `"ready"` throughout and only
transitions to `"down"` simultaneously with the actual reboot — too late to be
useful. The message string is the only reliable early signal for install.

**Uninstall** — no consistent `Message` signal observed. `DAService State`
transitions to `"down"` simultaneously with the reboot broadcast. This is the
reliable detection signal for uninstall across all tested platforms (Azure,
physical appliance, VMware).

**Upgrade** — `DAService State` transitions to `"down"` at the end of stage 1,
before the reboot fires. Returns `status: reboot_pending` — see Two-Stage Upgrade
section below.

| Action Type | Signal | Timing |
|---|---|---|
| Install | `Message: "Going to reboot:"` | ~30-90 seconds before reboot |
| Uninstall | `DAService State: "down"` | Simultaneous with reboot |
| Upgrade | `DAService State: "down"` | End of stage 1, before reboot |

**`reboot_delay` must be set** (30 seconds is the default and recommended minimum)
to guarantee at least one poll cycle captures the install message signal before
the host goes down. For uninstall and upgrade, `reboot_delay` provides a buffer
between the operation completing and the reboot firing.

Real captured sequence for an install:
```
19:09:48  Progress: 100, Status: "in progress", Message: "Going to reboot:"
19:09:53  Progress: 100, Status: "in progress", Message: "Going to reboot:"
  ... (polling continues) ...
19:10:30  Progress: 100, Status: "in progress", Message: ""
19:10:40  Broadcast: "The system is going down for reboot NOW!"
19:10:41  DAService State: "down"
```

Real captured sequence for an uninstall:
```
21:05:44  Progress: 100, Status: "in progress", Message: "Uninstalling:"
21:05:49  Progress: 100, Status: "in progress", Message: "Uninstalling:"
21:05:52  Broadcast: "The system is going down for reboot NOW!"
21:05:54  DAService State: "down", Progress: "N/A"
```

### Two-Stage Upgrade Model

Upgrade operations (Blink images and clean install packages) use a two-stage
process that reboots between stages. The module cannot survive the reboot — the
Python process running on the remote host is killed when the host reboots.

**Stage 1:** Prepares the new partition/image. Completes when `DAService State`
transitions to `"down"`. The module returns `status: reboot_pending` at this point.

**Stage 2:** Runs after reboot. Completes the upgrade. Observable via `da_status`
with `Installation in Progress: true` and `DAService State` progressing back to
`"ready"`.

Confirmed on: aarch64 Blink images, x86_64 version upgrade packages.

```
Stage 1 DA state transitions:
  Progress: 100   DAService State: ready   -- stage 1 done, DA still up
  Progress: ""    DAService State: ready   -- transitioning
  Progress: ""    DAService State: down    -- reboot imminent → module returns reboot_pending
                                           -- SSH drops, host reboots
                                           -- SSH returns
Stage 2 DA state transitions:
  Progress: 85    DAService State: ready   -- stage 2 running
  Progress: 100   DAService State: ready   -- stage 2 complete
  state: "Installed Successfully"          -- done
```

The playbook must handle the reboot and stage 2 monitoring — see Version Upgrade
Workflow in the Playbook section.

### Upgrade Reboot Quirk (Additional)

In addition to the general Progress/Status behavior, upgrade operations
have an additional reboot complication:
1. `Progress` reaches `"100"`, `Status` remains `"in progress"` (normal)
2. `DAService State` transitions to `"down"` — module returns `reboot_pending`
3. During reboot, SSH connection drops
4. SSH host key may change after reboot (version-dependent)
5. After reboot, stage 2 begins — monitor via `da_status` with `wait_for_ready`
6. `Installation in Progress` stays `true` until stage 2 completes
7. `DAService State` returns to `"ready"` when stage 2 is done

### Package State Strings

The `state` field in package info responses is a freeform human-readable
string to describe the package availability. Known values observed in
production:

| Condition | `state` value |
|---|---|
| Not yet downloaded | `"Available for download"` |
| Downloaded, not installed | `"Available for Install"` |
| Installed | `"Installed Successfully"` |

Use `isInRepository` (boolean) for reliable download status checks. For
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
- `state` — human-readable status string. See Package State Strings section
  above. Not used for programmatic checks.
- `isInRepository` — `false` when the package is known but not yet downloaded;
  becomes `true` after download completes. This is the reliable boolean for
  checking download status.
- `isBlinkImage` — `true` for Blink format images (aarch64 appliances and
  newer x86_64 packages). Blink images use the two-stage upgrade process.
- `requiresReboot` — whether installation triggers a reboot
- `children` / `parents` — package dependency chain between takes
- `packageType` — e.g. `"Wrapper"` for Jumbo bundles, `"Major Version"` for upgrades
- `product` — e.g. `"CPUpdates"` for Jumbos, `"Major"` for version upgrades
- **`isHfa`** — Despite the name, this is `false` even on actual Jumbo HFA
  packages. Do not use for identification. Use `tag.importance` and/or
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
- **Latest** — next candidate release. Identified by `category == "jumbo"`
  AND no `tag.importance` set AND not yet installed. Not always available.
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
11.   DAService State transitions to "down" ← module returns reboot_pending
12.   SSH drops, host reboots
13.   SSH host key may have changed
14.   Playbook: wait_for_connection until SSH returns
15.   Playbook: da_status wait_for_ready=true → monitors stage 2
16.   stage 2 completes, Installation in Progress returns false
17.   If failure, system MAY auto-revert (not guaranteed)
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
├── CHANGELOG.md
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
from here. Handles CLI execution, JSON parsing (including key normalization
and embedded-JSON-in-Message), action polling, and all da_cli behavioral
quirks.

**Key responsibilities:**
- `run()` — execute any da_cli subcommand, parse JSON, normalize keys;
  detects plain text `"Error: ..."` output (rc=1) for clean invalid-argument errors
- `poll_action()` — poll `get_status_of_action` until completion; handles
  Progress/Status quirks, reboot-imminent detection via message strings and
  `DAService State: "down"`, and upgrade `reboot_pending` return
- `run_action()` — convenience wrapper combining `run()` + `poll_action()`
- `check_for_updates()` — fires the command and polls `da_status` until
  Update Status returns to `"done"` or `"not allowed"`
- `find_recommended_jumbo()` / `find_latest_jumbo()` — package
  auto-detection helpers
- `_is_reboot_imminent()` — detects reboot-imminent message strings by
  action type (install: `"Going to reboot:"`)

### Module: `da_status`

Read-only module for agent status, build number, and reboot state.

**Returns:** `da_status` (raw dict), `build_number`, `service_state`, `ready` (bool),
`pending_reboot` (bool or None on older builds), `installation_in_progress`, `update_status`

**Options:** `wait_for_ready` (bool) — poll until DA is idle before returning.
`timeout` (int, default 120).

**Note:** `Update Status: "not allowed"` (hosts without Check Point Cloud access)
is treated as a valid ready state and does not block `wait_for_ready`.

### Module: `da_package_info`

Read-only module for querying the package catalog.

**Query modes (mutually exclusive):**
- `name` — single package by filename; `fail_json` if not found (rc=3 JSON error)
  or invalid name (rc=1 plain text error)
- `jumbo: recommended|latest` — auto-detect Jumbo HFA by release train
- `category: jumbo|major|misc` — filter all packages by category
- default — list packages with optional `status` filter

**Returns:** `package` (dict) or `packages` (list), `found` (bool), `count` (int)

**Note:** `jumbo` mode returns `package` (singular dict), not `packages` (list).
Use bracket notation for hyphenated keys in Jinja2: `result['warning-install']`.

### Module: `da_package`

The main workhorse — all state-changing package operations with built-in polling
and idempotency.

**States:**
- `downloaded` — ensure package is in local repository (idempotent via `isInRepository`)
- `private_download` — download unpublished package via `add_private_package`
- `imported` — import a file already on the host filesystem (requires `location`)
- `verified` — run pre-install verification; returns `verify_details` and surfaces
  `warnings` via Ansible's `[WARNING]` mechanism; never sets `changed`
- `verify_uninstall` — check uninstall eligibility; returns `verify_details`;
  never sets `changed`; catches dependency blocks before uninstall attempt
- `installed` — download + verify + install; idempotent via normalized package state
- `upgraded` — verify + upgrade; returns `status: reboot_pending` after stage 1;
  playbook must handle `wait_for_connection` and stage 2 monitoring
- `absent` — verify_uninstall + uninstall if installed, delete from repo if
  downloaded, no-op if not present

**Key options:**
- `reboot_delay` (int, default 30) — **required for reboot operations**; creates the
  polling window where reboot-imminent signals are visible before the host goes down
- `verify_before_install` (bool, default true) — auto-verify before install/upgrade
- `verify_before_uninstall` (bool, default true) — auto-verify before uninstall;
  catches dependency blocks (e.g. newer take installed on top)
- `refresh` (bool) — run `check_for_updates` before the operation
- `poll_interval` (int, default 5) — 5 seconds is required to reliably detect
  the ~15-second `DAService State: "down"` window before upgrade reboot
- `timeout` (int, default 900)

### Module: `da_command`

Low-level escape hatch for any `da_cli` subcommand not covered by the other modules.

**Options:** `command` (required), `wait` (bool, default true — poll if action command),
`parse_message` (bool), `changed` (bool, default null — override changed detection),
`poll_interval`, `timeout`

**Note:** `check_for_updates` via `da_command` will NOT poll correctly — it returns
Action ID `-1` and `run_action()` returns immediately for non-action commands.
Use `da_package` with `refresh: true` or `da_status` to monitor update completion.

---

## Playbook Patterns

### Simple Install (Auto-detect Recommended Jumbo)

```yaml
- name: Install latest Jumbo HFA
  hosts: firewalls
  gather_facts: false

  tasks:
    - name: Wait for DA to be ready
      webfargo.check_point.da_status:
        wait_for_ready: true
        timeout: 120

    - name: Install Recommended Jumbo HFA
      webfargo.check_point.da_package:
        state: installed
        refresh: true
        timeout: 1800
      register: install_result

    - name: Show result
      ansible.builtin.debug:
        var: install_result
```

### Controlled Step-by-Step Install with Reboot Handling

```yaml
- name: Jumbo HFA installation workflow
  hosts: firewalls
  gather_facts: false

  tasks:
    - name: Wait for DA to be ready
      webfargo.check_point.da_status:
        wait_for_ready: true
        timeout: 120

    - name: Find Recommended Jumbo HFA
      webfargo.check_point.da_package_info:
        jumbo: recommended
        refresh: true
      register: jumbo

    - name: Fail if no Jumbo found
      ansible.builtin.fail:
        msg: "No Recommended Jumbo HFA available"
      when: not jumbo.found

    - name: Show what we'll install
      ansible.builtin.debug:
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
      ansible.builtin.debug:
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
          ansible.builtin.wait_for:
            host: "{{ inventory_hostname }}"
            port: 22
            state: stopped
            delay: 10
            timeout: 120
          delegate_to: localhost

        - name: Wait for SSH to come back
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: "{{ 15 if ckp_facts.cloud_info.platform | default('') == 'azure' else 30 }}"
            sleep: 5
            timeout: 600
      rescue:
        - name: Wait for SSH to come back (rescue)
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 10
            sleep: 5
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
    - name: Wait for DA to be ready
      webfargo.check_point.da_status:
        wait_for_ready: true
        timeout: 120

    - name: Copy hotfix to host
      ansible.builtin.copy:
        src: "{{ hotfix_src }}"
        dest: "/var/tmp/{{ hotfix_file }}"

    - name: Import into DA repository
      webfargo.check_point.da_package:
        name: "{{ hotfix_file }}"
        state: imported
        location: /var/tmp

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
          ansible.builtin.wait_for:
            host: "{{ inventory_hostname }}"
            port: 22
            state: stopped
            delay: 10
            timeout: 120
          delegate_to: localhost

        - name: Wait for SSH to come back
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: "{{ 15 if ckp_facts.cloud_info.platform | default('') == 'azure' else 30 }}"
            sleep: 5
            timeout: 600
      rescue:
        - name: Wait for SSH to come back (rescue)
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 10
            sleep: 5
            timeout: 600
```

### Jumbo HFA Install — Reboot Handling Notes

The `da_package` module detects the reboot-imminent signal (`"Going to reboot:"` in
the Message field at Progress 100) and returns a clean result before the host goes
down. **`reboot_delay` must be set** (default 30 seconds) to guarantee the signal
is visible during polling.

After the module returns, use `wait_for` + `wait_for_connection` to handle the
reboot window. Do NOT use `ansible.builtin.reboot` — the host is already rebooting
and Ansible does not need to trigger it.

For uninstall operations, `DAService State: "down"` fires simultaneously with the
reboot — use `wait_for state: stopped` to detect the SSH drop cleanly rather than
relying on a fixed `delay`.

**Cloud-aware delay:** Azure VMs reboot significantly faster than physical hardware.
Use `ckp_facts.cloud_info.platform` (from `gather_facts` module) to set an
appropriate delay:

```yaml
delay: "{{ 15 if ckp_facts.cloud_info.platform | default('') == 'azure' else 30 }}"
```

**Do not use `delegate_to: localhost`** for `wait_for_connection` tasks. Use
`delegate_to: localhost` only for `wait_for state: stopped` TCP checks, where
the Ansible controller needs to probe the host's port directly.

### Version Upgrade Workflow

Upgrades use a two-stage process and require `ignore_errors: true` on the upgrade
task to handle platforms where the reboot signal may not be observed before SSH
drops. The module returns `status: reboot_pending` when stage 1 completes cleanly.

```yaml
- name: Upgrade Check Point version
  hosts: firewalls
  gather_facts: false

  vars:
    upgrade_package: "Check_Point_R82_Upgrade_Package.tgz"

  tasks:
    - name: Wait for DA to be ready
      webfargo.check_point.da_status:
        wait_for_ready: true
        timeout: 120

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

    # ignore_errors required: module may fail with UNREACHABLE if SSH drops
    # before DAService State "down" is observed (platform-dependent behavior)
    - name: Execute upgrade
      webfargo.check_point.da_package:
        name: "{{ upgrade_package }}"
        state: upgraded
        verify_before_install: false  # already verified
        timeout: 3600
      register: upgrade_result
      ignore_errors: true

    - name: Wait for reboot and stage 2
      when: >
        upgrade_result.status | default('') == "reboot_pending" or
        upgrade_result.failed | default(false)
      block:
        - name: Wait for SSH to come back
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 30
            sleep: 15
            timeout: 600

        - name: Wait for stage 2 completion
          webfargo.check_point.da_status:
            wait_for_ready: true
            timeout: 1800
      rescue:
        - name: Wait for SSH to come back (rescue)
          ansible.builtin.wait_for_connection:
            connect_timeout: 3
            delay: 60
            sleep: 15
            timeout: 600

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
install. If a package is incompatible with the host's DA version, it may
fail to import or may simply not appear in `packages_info` results at all.
There is no reliable programmatic way to check compatibility — it may be
logged, but the log format isn't stable enough to parse. The modules do not
attempt to detect or handle this; if you hit it, the action will fail with
whatever error `da_cli` returns and the module will surface that message.

**`show_progress`:** Reads from a semaphore file written by another process.
Not useful for automation; `get_status_of_action` is the correct polling
mechanism.

**`get_version`:** Always returns `{"version": "1"}`. Use
`get_build_number()` which falls back through `da_status` → `dbget`.

**`is_pending_reboot`:** Recent addition to `da_cli`. May not exist on older
DA builds. The `da_status` module handles this gracefully (returns `None`
if unavailable).

**`DABuildNumber` in `da_status`:** Also a newer addition. Not present in
older DA builds. The `get_build_number()` method falls back to
`dbget installer:da_build`.

**`Update Status: "not allowed"`:** Hosts without Check Point Cloud access
permanently show `"not allowed"` for Update Status. This is treated as a
valid ready state — it does not indicate an in-progress operation.

**Package state strings are freeform:** The `state` field in package info
responses is not a stable enum. Known values include `"Available for download"`,
`"Available for Install"`, and `"Installed Successfully"`. Always normalize
before comparing — never do a direct string equality check against `state`.
Use `isInRepository` for download status and `state.lower().startswith("installed")`
for install status.

**Reboot-imminent signals vary by action type:** Install uses the
`"Going to reboot:"` message string (~30-90 seconds before reboot). Uninstall
and upgrade use `DAService State: "down"` (simultaneous with or just before
reboot). The `_is_reboot_imminent()` helper covers install; `DAService State`
detection covers uninstall and upgrade. Both are needed — neither is universal.

**`reboot_delay` is effectively required for reboot operations:** Without it,
the host may reboot before the module receives a clean result. The default
is 30 seconds. Lower values may work but reduce the polling window for
reboot-imminent signal detection.

**`poll_interval` default is 5 seconds:** Required to reliably detect the
~15-second `DAService State: "down"` window before upgrade reboot. Higher
values risk missing the signal entirely.

**Two-stage upgrade behavior:** Applies to Blink images (`isBlinkImage: true`)
and clean install packages (`category: major`). The module cannot survive the
reboot between stages and returns `status: reboot_pending`. The playbook must
handle `wait_for_connection` and stage 2 monitoring via `da_status` with
`wait_for_ready: true`. Use `ignore_errors: true` on the upgrade task to handle
platforms where `DAService State: "down"` is not observed before SSH drops.

**Blink image upgrade interrupted by `dastart`:** Manually restarting the DA
service (`dastart`) during stage 2 of a Blink upgrade will interrupt the action
and leave it in `"interrupted"` state. The host should be unaffected (still on
old version) but the action cannot be resumed — re-run the upgrade from scratch.
Do not restart the DA service while `Installation in Progress: true`.

**Verify "failure" for installed packages:** A verify returning
`Status: "failure"` with `message-code: "DEPENDENCY"` means the package is
already installed — this is an idempotency signal, not an actual error.

**`verify_uninstall` dependency blocks:** `verify_uninstall` returning
`Status: "failure"` with a message like "A newer version is installed on top
of..." means the package cannot be uninstalled until the newer take is
removed first. `verify_before_uninstall: true` (the default) surfaces this
before attempting the uninstall.

**`da_package_info` name query errors:** `package_info package=<n>` returns
rc=3 with a JSON "No such package" message for unknown package names, and
rc=1 with a plain text "Error: ..." message for invalid names (wrong extension,
etc.). Both are handled as `fail_json` with clear error messages.

**`wait_for_connection` vs `wait_for` for reboot handling:** Use
`wait_for state: stopped` with `delegate_to: localhost` to detect SSH going
down, then `wait_for_connection` (no `delegate_to`) to wait for the host to
come back. `wait_for_connection` without the `stopped` pre-check may probe
while SSH is still up and declare success before the reboot actually fires —
particularly for uninstall where `DAService State: "down"` fires simultaneously
with the reboot and the SSH drop may be delayed.

**Azure VM reboot speed:** Azure VMs reboot significantly faster than physical
hardware. The entire down-and-back cycle can complete within the `delay` window
of `wait_for_connection`, causing it to miss the reboot entirely. Use
`ckp_facts.cloud_info.platform` from the `gather_facts` module to apply a
shorter delay for Azure hosts.
