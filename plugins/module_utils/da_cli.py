#!/usr/bin/python
# -*- coding: utf-8 -*-
# plugins/module_utils/da_cli.py

# Copyright: (c) 2026, Webfargo Data Security, Inc.
# GNU General Public License v3.0+

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

    def _is_reboot_imminent(self, message):
        """
        Check if the action message signals an imminent reboot.
        da_cli uses different messages per action type:
          - Install:   "Going to reboot:"
          - Uninstall: "Uninstallation Complete"
          - Upgrade:   TBD
        """
        msg = message.lower()
        return any(msg.startswith(trigger) for trigger in (
            "going to reboot",
            "uninstallation complete",
        ))

    def poll_action(self, action_id, poll_interval=10, timeout=None,
                    is_upgrade=False):
        """
        Poll get_status_of_action until completion or timeout.

        IMPORTANT: Progress reaching "100" does NOT mean the action is
        complete. Any action type (download, install, verify, upgrade)
        can show Progress "100" while Status remains "in progress" —
        always wait for Status to become "success" or "failure".

        Reboot-triggering actions (install, uninstall, upgrade) emit a
        reboot-imminent message in the Message field at Progress 100
        while Status remains "in progress". Known signals:
          - Install:   "Going to reboot:"
          - Uninstall: "Uninstallation Complete"
          - Upgrade:   TBD
        When detected, the action is treated as successful and the
        module returns before the host goes down. This requires
        reboot_delay to be set on the da_cli command so at least one
        poll cycle captures the message before the reboot fires.

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
                    reboot_detected = True
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    continue
                elif is_upgrade and reboot_detected:
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    continue
                else:
                    raise

            current_status = status.get("status", "unknown")
            progress = status.get("progress", "0")
            message = status.get("message", "") or ""

            try:
                progress_int = int(progress) if progress else 0
            except (ValueError, TypeError):
                progress_int = 0
            if progress_int >= 100:
                progress_hit_100 = True

            if current_status == "success":
                return self.parse_embedded_message(status)

            if current_status == "failure":
                raise DaCliError(
                    f"Action {action_id} failed: "
                    f"{status.get('message', 'no message')}",
                    stdout=json.dumps(status),
                )

            # Reboot imminent — install/uninstall succeeded, reboot countdown
            # started. Exit now before the connection drops.
            # Requires reboot_delay to be set so we get at least one poll
            # cycle with this message before the host goes down.
            if (progress_hit_100
                and current_status == "in progress"
                and self._is_reboot_imminent(message)):
                status["status"] = "success"

                return self.parse_embedded_message(status)

            # Upgrade quirk: Status stays "in progress" at Progress 100,
            # then system reboots. Don't treat this as completion.
            if is_upgrade and progress_hit_100 and current_status == "in progress":
                pass

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
                return pkg.get("state", "").lower().startswith("installed")

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
