# Changelog

All notable changes to the `webfargo.check_point` Ansible collection are documented here.

## [0.7.0] - 2026-06-10

### Added

- `da_package` — new `state: verify_uninstall` — runs `da_cli verify_uninstall` and returns
  eligibility result; informational, never sets `changed`
- `da_package` — new `verify_before_uninstall` parameter (default `true`) — automatically runs
  `verify_uninstall` before uninstalling a package; catches dependency blocks and ordering
  requirements (e.g. newer take installed on top) before the uninstall attempt
- `da_package` — `state: verified` now surfaces warnings via Ansible's `[WARNING]` display
  mechanism; `warning-install` and `warning-upgrade` warnings are deduplicated and returned
  as top-level `warnings` list
- `da_package` — `state: installed` and `state: upgraded` now preserve verify warnings through
  `result.update(action_result)` so they are not overwritten by the action response
- `gather_facts` — new `gather_cloud_info()` method reads `/etc/cloud-version.json`
  (with fallback to `/etc/cloud-version`) to surface cloud platform metadata including
  `platform`, `release`, `take`, `license`, `deployment_method`, `template_name`,
  `template_version`, `template_type`; returns empty dict on non-cloud hosts

### Changed

- `da_cli.poll_action()` — added `DAService State: "down"` detection for uninstall operations;
  more reliable than message string alone since `"Uninstallation Complete"` is not consistently
  emitted across all package types and platforms
- `da_cli.poll_action()` — added `DAService State: "down"` detection for upgrade operations;
  returns `status: reboot_pending` when stage 1 of a two-stage upgrade completes; the module
  cannot survive the reboot — playbook must handle `wait_for_connection` and stage 2 monitoring
  via `da_status` with `wait_for_ready=true`
- `da_cli.poll_action()` — added `"interrupted"` to recognized failure status values; module
  now fails fast with a clear error rather than polling until timeout
- `da_cli.poll_action()` — added enriched error message when SSH drops during upgrade reboot
  window after Progress hit 100 but before `DAService State: "down"` was observed
- `da_cli.poll_action()` — `not is_upgrade` guard added to `_is_reboot_imminent` check;
  prevents premature exit on `"Going to reboot:"` signal during upgrade stage 1 since upgrade
  requires the `DAService State: "down"` signal instead
- `da_cli.run()` — plain text `"Error: ..."` output to stdout (rc=1) now produces a clean
  error message extracting the first line rather than a generic `da_cli command failed` error
- `da_package_info.query_by_name()` — `rc=3` JSON `"No such package"` response now returns
  `fail_json` with a clear package-not-found message instead of a generic da_cli error
- `da_status.is_ready()` — `Update Status: "not allowed"` now treated as a valid ready state;
  hosts without Check Point Cloud access permanently show `"not allowed"` and would otherwise
  never pass the ready check
- `da_package` — `poll_interval` default changed from 15 to 5 seconds; required to reliably
  detect the ~15-second `DAService State: "down"` window before upgrade reboot
- `da_package` — `reboot_delay` default set to 30 seconds; creates the polling window where
  reboot-imminent signals are visible before the host goes down

### Fixed

- `da_cli.is_package_installed()` — fixed raw string comparison `state == "installed"` to
  use `state.lower().startswith("installed")`; da_cli returns `"Installed Successfully"` not
  `"installed"`
- `da_package.normalize_pkg_state()` — fixed state normalization for all three known da_cli
  state strings: `"Available for download"` → `not_downloaded`, `"Available for Install"` →
  `available`, `"Installed Successfully"` → `installed`

### Documentation

- Design document (`cpda_design.md`) — major update: source code blocks removed; added
  Reboot-Imminent Signals section with known message strings table; added Package State Strings
  section documenting freeform state values; added two-stage upgrade model; updated all workflow
  examples to use validated `wait_for_connection` + block/rescue pattern; added Blink image
  upgrade Known Limitations; added `wait_for_connection` vs `wait_for` guidance
- `da_package` DOCUMENTATION — added `verify_uninstall` state; updated `absent` to document
  `verify_before_uninstall`; updated `upgraded` to document two-stage reboot handling and
  `ignore_errors` requirement; updated `poll_interval` and `reboot_delay` descriptions
- `da_package` EXAMPLES — added upgrade two-task pattern with `ignore_errors`, `reboot_pending`
  handling, and stage 2 monitoring; added `verify_uninstall` example
- `da_package` RETURN — added `reboot_pending` as documented value for `status`; updated
  `verify_details` returned conditions; added `warnings` documentation

## [0.1.0 — 0.6.0]

Earlier versions predating this changelog. Key milestones:

- Initial collection with `da_status`, `da_package`, `da_package_info`, `da_command` modules
- `DaCliClient` / `DaCliError` shared module utils
- `gather_facts` module with hardware, SIC, host type, version, take info gathering
- Idempotent state machine for all `da_package` states
- Check mode support across all modules
- `_is_reboot_imminent()` helper for install/uninstall reboot signal detection
- Package state normalization (`normalize_pkg_state()`)
- `da_status` refactor with `get_status()`, `get_pending_reboot()`, `wait_until_ready()` helpers
- `da_package_info` refactor with per-query-mode handler functions
- `da_package` refactor with per-state handler functions
- Published to Ansible Galaxy under `webfargo` namespace

