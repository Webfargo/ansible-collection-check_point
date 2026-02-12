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
- `get_version` — **useless**, always returns `{"version": "1"}`; use `DABuildNumber` from `da_status` JSON output instead
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
- `"Action ID"` is a string, not an integer (Check Point's choice, not ours). It is safely convertible to `int` for arithmetic or comparison. The value `"-1"` is a sentinel meaning "not an action command" — not an error.
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

### get_version Is Useless

`da_cli get_version` returns a meaningless static value:
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

### Upgrade Reboot Quirk (Additional)

**On top of** the general Progress/Status behavior, upgrade operations
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
- `state` — human-readable status string (e.g. `"Available for download"`,
  `"installed"`). Informational; prefer `isInRepository` for programmatic checks.
- `isInRepository` — `false` when the package is known but not yet downloaded;
  becomes `true` after download completes. This is the reliable boolean for
  checking download status.
- `requiresReboot` — whether installation triggers a reboot
- `children` / `parents` — package dependency chain between takes
- `packageType` — e.g. `"Wrapper"` for Jumbo bundles, `"Major Version"` for upgrades
- `product` — e.g. `"CPUpdates"` for Jumbos, `"Major"` for version upgrades
- **`isHfa`** — **UNRELIABLE.** Despite the name, this is `false` even on
  actual Jumbo HFA packages. Do not use for identification. Use
  `tag.importance` and/or `category` instead.
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
  Despite the confusing naming, `tag.importance == "latest"` means "Recommended"
  in Check Point's terminology.
- **Latest** — public beta, next candidate release. Identified by
  `category == "jumbo"` AND no `tag.importance` set AND not yet installed.
  Not always available. If multiple candidates exist, select highest `build`.

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
10. get_status_of_action          → poll until install complete (Progress 100, success)
11. (host reboots after reboot_delay seconds)
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
1. (scp file to host)
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
├── plugins/
│   ├── module_utils/
│   │   └── da_cli.py                  # Shared CLI execution & JSON handling
│   └── modules/
│       ├── da_status.py           # da_status, build number, is_pending_reboot
│       ├── da_package_info.py    # packages_info, package_info
│       ├── da_package.py          # download/import/verify/install/uninstall/delete
│       └── da_command.py          # Low-level: run arbitrary da_cli commands
├── roles/
│   ├── gather_facts/                  # existing ckp_gather_facts role
│   └── cpda/                          # optional: thin workflow role using modules
```

### Module Utils: `da_cli.py`

This is the core — all modules share this for CLI execution, JSON parsing, and action polling.

```python
# plugins/module_utils/da_cli.py

import json
import time


class DaCliError(Exception):
    """Custom exception for da_cli failures."""
    def __init__(self, message, rc=None, stdout=None, stderr=None):
        super().__init__(message)
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr


class DaCliClient:
    """
    Wrapper around the Check Point Deployment Agent CLI (da_cli).

    Handles command execution, JSON response parsing (including the
    annoying caps-and-spaces key names), action polling, and the
    embedded-JSON-in-Message quirk.
    """

    # Normalize da_cli's "Caps With Spaces" keys to snake_case
    KEY_MAP = {
        "Action ID": "action_id",
        "Action Type": "action_type",
        "DAService State": "da_service_state",
        "ExtendedMessage": "extended_message",
        "Message": "message",
        "Package": "package",
        "Progress": "progress",
        "Status": "status",
    }

    def __init__(self, module, timeout=300):
        self.module = module
        self.timeout = timeout

    def run(self, subcommand, raw=False):
        """
        Execute a da_cli subcommand and return parsed JSON.

        Args:
            subcommand: The da_cli subcommand string (e.g. "da_status")
            raw: If True, return the raw dict without key normalization

        Returns:
            dict with parsed JSON response (keys normalized to snake_case
            unless raw=True)

        Raises:
            DaCliError on non-zero exit or unparseable output
        """
        cmd = f"da_cli {subcommand}"
        rc, stdout, stderr = self.module.run_command(cmd)

        if rc != 0:
            raise DaCliError(
                f"da_cli command failed (rc={rc}): {stderr.strip()}",
                rc=rc, stdout=stdout, stderr=stderr,
            )

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise DaCliError(
                f"Failed to parse da_cli JSON output: {e}",
                stdout=stdout,
            )

        if raw:
            return data

        return self._normalize_keys(data)

    def _normalize_keys(self, data):
        """
        Normalize top-level da_cli response keys to snake_case.

        Only normalizes known action-response keys. Package info
        responses pass through with original camelCase keys since
        those are already reasonable for Ansible consumption.
        """
        if not isinstance(data, dict):
            return data

        result = {}
        for key, value in data.items():
            normalized = self.KEY_MAP.get(key, key)
            result[normalized] = value
        return result

    def parse_embedded_message(self, response):
        """
        Some da_cli responses (notably Verify) embed JSON as a string
        inside the "Message" field. This extracts and parses it.

        Returns the original response dict with 'message' replaced
        by the parsed structure, or unchanged if Message isn't JSON.
        """
        key = "message" if "message" in response else "Message"
        msg = response.get(key, "")

        if not msg or not isinstance(msg, str):
            return response

        try:
            parsed = json.loads(msg)
            result = dict(response)
            result[key] = parsed
            return result
        except (json.JSONDecodeError, TypeError):
            return response

    def is_action_command(self, response):
        """Check if the response is from an action command (has real Action ID)."""
        action_id = response.get("action_id", response.get("Action ID", "-1"))
        return str(action_id) != "-1"

    def poll_action(self, action_id, poll_interval=10, timeout=None,
                    is_upgrade=False):
        """
        Poll get_status_of_action until completion or timeout.

        IMPORTANT: Progress reaching "100" does NOT mean the action is
        complete. Any action type (download, install, verify, upgrade)
        can show Progress "100" while Status remains "in progress" —
        always wait for Status to become "success" or "failure".

        Args:
            action_id: The action ID to monitor
            poll_interval: Seconds between polls (default 10)
            timeout: Override instance timeout for this poll
            is_upgrade: If True, use upgrade-specific completion logic.
                Upgrade packages have an additional quirk on top of the
                normal Progress/Status behavior: the system reboots
                while Status is still "in progress", da_cli becomes
                unreachable, and after reboot the same Action ID can
                be polled again as Progress drops back and climbs to
                100 a second time. This flag enables handling of SSH
                connection failures during that reboot window.

        Returns:
            Final action status response (normalized)

        Raises:
            DaCliError if action fails or times out
        """
        effective_timeout = timeout or self.timeout
        elapsed = 0
        reboot_detected = False
        progress_hit_100 = False

        while elapsed < effective_timeout:
            try:
                status = self.run(
                    f"get_status_of_action actionID={action_id}"
                )
            except DaCliError:
                if is_upgrade and progress_hit_100:
                    # Expected: host is rebooting after upgrade reached 100
                    reboot_detected = True
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    continue
                elif is_upgrade and reboot_detected:
                    # Still rebooting, keep waiting
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    continue
                else:
                    raise

            current_status = status.get("status", "unknown")
            progress = status.get("progress", "0")

            # Track if we've seen progress hit 100
            # Progress can be an empty string (e.g. during delete)
            try:
                progress_int = int(progress) if progress else 0
            except (ValueError, TypeError):
                progress_int = 0
            if progress_int >= 100:
                progress_hit_100 = True

            if current_status == "success":
                return self.parse_embedded_message(status)

            # "failure" is the actual key value from da_cli
            if current_status == "failure":
                raise DaCliError(
                    f"Action {action_id} failed: "
                    f"{status.get('message', 'no message')}",
                    stdout=json.dumps(status),
                )

            # Upgrade quirk: Status stays "in progress" at Progress 100,
            # then system reboots. Don't treat this as completion.
            if is_upgrade and progress_hit_100 and current_status == "in progress":
                # Upgrade is about to reboot — keep polling
                pass

            # Still in progress
            time.sleep(poll_interval)
            elapsed += poll_interval

        raise DaCliError(
            f"Action {action_id} timed out after {effective_timeout}s "
            f"(last progress: {progress}%)"
        )

    def run_action(self, subcommand, poll_interval=10, timeout=None,
                   is_upgrade=False):
        """
        Execute an action command and poll until completion.

        Convenience method that combines run() + poll_action().

        Args:
            subcommand: da_cli subcommand string
            poll_interval: Seconds between status polls
            timeout: Max seconds to wait
            is_upgrade: Pass True for upgrade operations to handle
                the reboot-during-progress quirk

        Returns:
            Final action status response
        """
        response = self.run(subcommand)

        action_id = response.get("action_id", "-1")
        if str(action_id) == "-1":
            # Not an action command, return immediately
            return response

        return self.poll_action(
            action_id,
            poll_interval=poll_interval,
            timeout=timeout,
            is_upgrade=is_upgrade,
        )

    # ----- Convenience methods -----

    def get_da_status(self):
        """Get current DA status via da_status command (raw keys)."""
        return self.run("da_status", raw=True)

    def get_build_number(self):
        """
        Get the DA build number.

        Tries DABuildNumber from da_status first (available in newer
        DA builds), falls back to `dbget installer:da_build` for
        older versions that don't include it. Never uses get_version,
        which returns a useless static "1".
        """
        status = self.get_da_status()
        build = status.get("DABuildNumber")
        if build:
            return build

        # Fallback for older DA builds: query config database
        try:
            rc, stdout, stderr = self.module.run_command(
                "dbget installer:da_build"
            )
            if rc == 0 and stdout.strip():
                return stdout.strip()
        except Exception:
            pass

        return None

    def is_ready(self):
        """
        Check if the DA service is ready and idle.

        Defensive about missing keys since da_status response fields
        vary across DA build versions.
        """
        status = self.get_da_status()
        return (
            status.get("DAService State") == "ready"
            and not status.get("Installation in Progress", False)
            and status.get("Update Status", "done") == "done"
        )

    def check_for_updates(self, poll_interval=10, timeout=None):
        """
        Run check_for_updates and wait for completion.

        check_for_updates is deceptive: it returns Action ID -1
        (non-action pattern) but is actually async. The command
        returns immediately, and progress must be monitored via
        da_status by polling "Update Status" until it returns to
        "done".
        """
        effective_timeout = timeout or self.timeout

        # Fire off the update check
        self.run("check_for_updates")

        # Poll da_status until Update Status returns to "done"
        elapsed = 0
        update_status = ""
        while elapsed < effective_timeout:
            status = self.get_da_status()
            update_status = status.get("Update Status", "")

            if update_status == "done":
                return status

            # Still working (e.g. "Validating candidates 90%")
            time.sleep(poll_interval)
            elapsed += poll_interval

        raise DaCliError(
            f"check_for_updates timed out after {effective_timeout}s "
            f"(last Update Status: {update_status})"
        )

    def get_packages(self, status_filter=None):
        """List packages, optionally filtered by status."""
        cmd = "packages_info"
        if status_filter and status_filter != "all":
            cmd += f" status={status_filter}"
        data = self.run(cmd, raw=True)
        return data.get("packages", [])

    def get_package(self, package_name):
        """Get info for a single package by filename."""
        return self.run(
            f"package_info package={package_name}", raw=True
        )

    def is_package_installed(self, package_name):
        """Check if a specific package is installed."""
        for pkg in self.get_packages():
            if pkg.get("filename") == package_name:
                return pkg.get("state") == "installed"
        return False

    def is_package_in_repository(self, package_name):
        """Check if a package is downloaded/available locally."""
        for pkg in self.get_packages():
            if pkg.get("filename") == package_name:
                return pkg.get("isInRepository", False)
        return False

    def find_recommended_jumbo(self):
        """
        Find the Recommended Jumbo HFA.

        Check Point marks the current Recommended release with
        tag.importance == "latest" (confusingly). This is the stable,
        production-ready Jumbo HFA.

        Filters: category == "jumbo", not yet installed (no installedOn
        key), and tag.importance == "latest".

        Returns the package dict, or None if not found (e.g. the
        Recommended package is already installed and no newer one
        has been tagged yet).
        """
        for pkg in self.get_packages():
            if (pkg.get("category") == "jumbo"
                    and "installedOn" not in pkg
                    and pkg.get("tag", {}).get("importance") == "latest"):
                return pkg
        return None

    def find_latest_jumbo(self):
        """
        Find the Latest (beta/pre-release) Jumbo HFA.

        Check Point publishes a "Latest" train that is effectively a
        public beta — the next package to potentially become the
        Recommended release. These packages have category == "jumbo"
        but do NOT have the tag.importance field set.

        Filters: category == "jumbo", not yet installed (no installedOn
        key), and NO tag.importance set. If multiple candidates exist,
        returns the one with the highest build number.

        Returns the package dict, or None if no Latest package is
        currently available (this is normal — the Latest train is
        not always populated).
        """
        candidates = [
            pkg for pkg in self.get_packages()
            if (pkg.get("category") == "jumbo"
                and "installedOn" not in pkg
                and not pkg.get("tag", {}).get("importance"))
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: int(p.get("build", 0)))
```

---

### Module 1: `da_status`

Read-only module for agent status, build number, and reboot state.

```python
# plugins/modules/da_status.py

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

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.webfargo.check_point.plugins.module_utils.da_cli import (
    DaCliClient,
    DaCliError,
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
            # Poll until fully ready
            timeout = module.params["timeout"]
            elapsed = 0
            poll_interval = 10
            while elapsed < timeout:
                status = client.get_da_status()
                if (status.get("DAService State") == "ready"
                        and not status.get("Installation in Progress", False)
                        and status.get("Update Status") == "done"):
                    break
                import time
                time.sleep(poll_interval)
                elapsed += poll_interval
            else:
                module.fail_json(
                    msg=f"DA not ready after {timeout}s "
                        f"(state: {status.get('DAService State')}, "
                        f"update: {status.get('Update Status')})"
                )
        else:
            status = client.get_da_status()

        result["da_status"] = status
        result["build_number"] = client.get_build_number() or "unknown"
        result["service_state"] = status.get("DAService State", "unknown")
        result["installation_in_progress"] = status.get(
            "Installation in Progress", False
        )
        result["update_status"] = status.get("Update Status", "unknown")

        result["ready"] = (
            result["service_state"] == "ready"
            and not result["installation_in_progress"]
            and result["update_status"] == "done"
        )

        # Pending reboot check
        # Response when no reboot:
        #   {"Action ID": "0", "Message": "no reboot"}
        # Response when reboot pending:
        #   {"Action ID": "0", "Message": "reboot delayed for 30 seconds.",
        #    "Package": "mgmt_wrapper_HOTFIX_R82_JHF_T60_296_MAIN_GA_FULL.tgz"}
        # This command is a recent addition and may not exist on older
        # DA builds.
        try:
            reboot_data = client.run("is_pending_reboot", raw=True)
            msg = reboot_data.get("Message", "")
            is_pending = msg.lower() != "no reboot"
            result["pending_reboot"] = is_pending
            if is_pending:
                result["pending_reboot_message"] = msg
                result["pending_reboot_package"] = reboot_data.get(
                    "Package", ""
                )
        except DaCliError:
            # Command may not exist on older builds; not critical
            result["pending_reboot"] = None

    except DaCliError as e:
        module.fail_json(msg=str(e))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
```

---

### Module 2: `da_package_info`

Read-only module for querying packages — this replaces the `packages_info` and `package_info` commands.

```python
# plugins/modules/da_package_info.py

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

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.webfargo.check_point.plugins.module_utils.da_cli import (
    DaCliClient,
    DaCliError,
)


def find_recommended_jumbo(packages):
    """Find the Recommended Jumbo HFA (category=jumbo, not installed, tagged)."""
    for pkg in packages:
        if (pkg.get("category") == "jumbo"
                and "installedOn" not in pkg
                and pkg.get("tag", {}).get("importance") == "latest"):
            return pkg
    return None


def find_latest_jumbo(packages):
    """Find the Latest (beta) Jumbo HFA (category=jumbo, not installed, no tag)."""
    candidates = [
        pkg for pkg in packages
        if (pkg.get("category") == "jumbo"
            and "installedOn" not in pkg
            and not pkg.get("tag", {}).get("importance"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: int(p.get("build", 0)))


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
                default="all",
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
        # Optionally sync with remote repository first
        # check_for_updates is async despite returning Action ID -1;
        # client.check_for_updates() polls da_status until done
        if module.params["refresh"] and not module.check_mode:
            client.check_for_updates(timeout=module.params["timeout"])

        if module.params["name"]:
            # Single package query by name
            pkg_name = module.params["name"]
            data = client.run(
                f"package_info package={pkg_name}", raw=True
            )
            result["package"] = data
            result["found"] = True  # would have errored if not found

        elif module.params["jumbo"]:
            # Smart Jumbo HFA selection by train
            data = client.run("packages_info", raw=True)
            packages = data.get("packages", [])

            if module.params["jumbo"] == "recommended":
                jumbo = find_recommended_jumbo(packages)
            else:
                jumbo = find_latest_jumbo(packages)

            if jumbo:
                result["package"] = jumbo
                result["found"] = True
            else:
                result["package"] = {}
                result["found"] = False

        elif module.params["category"]:
            # Filter by package category
            data = client.run("packages_info", raw=True)
            packages = [
                pkg for pkg in data.get("packages", [])
                if pkg.get("category") == module.params["category"]
            ]
            result["packages"] = packages
            result["count"] = len(packages)
            result["found"] = len(packages) > 0

        else:
            # List packages with optional status filter
            status = module.params["status"]
            cmd = "packages_info"
            if status != "all":
                cmd += f" status={status}"

            data = client.run(cmd, raw=True)
            packages = data.get("packages", [])
            result["packages"] = packages
            result["count"] = data.get("numberOfPackages", len(packages))
            result["found"] = len(packages) > 0

    except DaCliError as e:
        module.fail_json(msg=str(e))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
```

---

### Module 3: `da_package`

The main workhorse — handles all state-changing package operations with built-in polling.

```python
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
```

---

### Module 4: `da_command`

Low-level escape hatch for any `da_cli` subcommand not covered by the other modules.

```python
# plugins/modules/da_command.py

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


```

---

## Playbook Comparison

### Before: Role Approach (Conceptual)

```yaml
# This is approximately what the role's tasks/main.yml does
# via shell/raw commands + register + json_query + set_fact

- name: Check for updates
  raw: da_cli check_for_updates
  register: _cfu_result

- name: Get packages info
  raw: da_cli packages_info
  register: _pkg_info_raw

- name: Parse packages
  set_fact:
    _packages: "{{ _pkg_info_raw.stdout | from_json }}"

- name: Find latest jumbo
  set_fact:
    _jumbo_package: >-
      {{ _packages.packages
         | selectattr('tag', 'defined')
         | selectattr('tag.importance', 'eq', 'latest')
         | first }}
  when: cpda_package is not defined

- name: Download package
  raw: "da_cli download package={{ _target_package }}"
  register: _download_result

- name: Parse download action ID
  set_fact:
    _download_action_id: "{{ (_download_result.stdout | from_json)['Action ID'] }}"

- name: Wait for download to complete
  raw: "da_cli get_status_of_action actionID={{ _download_action_id }}"
  register: _download_status
  until: (_download_status.stdout | from_json).Status == 'success'
  retries: 60
  delay: 15

# ... repeat for verify, install ...
# ... lots of YAML, fragile parsing, complex until/retries ...
```

### After: Module Approach

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
        reboot_delay: 120
      register: install

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
    hotfix_src: "/opt/ansible_shared/files/hotfixes/{{ hotfix_file }}"

  tasks:
    - name: Copy hotfix to host
      copy:
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
        reboot_delay: 60
        timeout: 1200
```

### Jumbo HFA Install with Reboot Handling

Jumbo HFA installs require a reboot. The `reboot_delay` parameter gives you
a window, but you still need to handle the actual reboot:

```yaml
- name: Install Jumbo HFA with reboot
  hosts: firewalls
  gather_facts: false

  tasks:
    - name: Install latest Jumbo HFA
      webfargo.check_point.da_package:
        state: installed
        refresh: true
        reboot_delay: 60
        timeout: 1800
      register: install_result

    - name: Wait for reboot
      ansible.builtin.reboot:
        reboot_timeout: 600
        # No reboot_command needed — da_cli triggers it after delay
        test_command: "da_cli da_status"
      when: install_result.changed

    - name: Verify post-install status
      webfargo.check_point.da_status:
      register: post_status
```

### Version Upgrade Workflow

Upgrades are the most complex operation due to the reboot-during-progress
behavior. The module handles polling through the reboot, but you should
use generous timeouts and handle potential SSH key changes:

```yaml
- name: Upgrade Check Point version
  hosts: firewalls
  gather_facts: false

  vars:
    upgrade_package: "Check_Point_R82_Upgrade_Package.tgz"

  tasks:
    - name: Copy upgrade package
      copy:
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
      debug:
        var: verify.warnings
      when: verify.warnings is defined

    - name: Confirm upgrade
      pause:
        prompt: "Proceed with upgrade? (Ctrl+C to abort)"

    - name: Execute upgrade
      webfargo.check_point.da_package:
        name: "{{ upgrade_package }}"
        state: upgraded
        verify_before_install: false  # already verified
        timeout: 3600  # upgrades can take a very long time
      register: upgrade_result

    # SSH host key may have changed after upgrade
    - name: Accept new SSH host key
      known_hosts:
        name: "{{ ansible_host }}"
        state: absent
      delegate_to: localhost

    - name: Verify post-upgrade status
      webfargo.check_point.da_status:
        detail: full
      register: post_upgrade
```

## Known Limitations & Edge Cases

**DA build version compatibility:** Not all hosts run the same DA build version,
and certain packages require a minimum DA build to import or install. The DA
does not auto-update itself (that's a separate mechanism outside scope). If a
package is incompatible with the host's DA version, it may fail to import or
may simply not appear in `packages_info` results at all. There is no reliable
programmatic way to check compatibility — it may be logged, but the log format
isn't stable enough to parse. The modules do not attempt to detect or handle
this; if you hit it, the action will fail with whatever error `da_cli` returns
and the module will surface that message.

**`show_progress`:** Reads from a semaphore file written by another process.
Not useful for automation; `get_status_of_action` is the correct polling
mechanism.

**`get_version`:** Always returns `{"version": "1"}`. Useless. Use
`get_build_number()` which falls back through `da_status` → `dbget`.

**`is_pending_reboot`:** Recent addition to `da_cli`. May not exist on older
DA builds. The `da_status` module handles this gracefully (returns `None`
if unavailable).

**`DABuildNumber` in `da_status`:** Also a newer addition. Not present in
older DA builds. The `get_build_number()` method falls back to
`dbget installer:da_build`.

**Upgrade reboot behavior:** Status stays `"in progress"` at Progress 100,
host reboots, SSH may drop, host key may change, Progress resets and climbs
again. This is confirmed by Check Point TAC as intentional behavior.

**Verify "failure" for installed packages:** A verify returning
`Status: "failure"` with `message-code: "DEPENDENCY"` means the package is
already installed — this is an idempotency signal, not an actual error.
