# Changelog

All notable changes to the `webfargo.check_point` Ansible collection are documented here.

## [0.8.0] - 2026-06-17

### Added

- `gather_facts` — new `cluster_state` subset and fact, parsed from `cphaprob state` output.
  Returns `ACTIVE`, `STANDBY`, or `unknown` for the local cluster member; returns `null`
  when the host is not a cluster member (`cluster` fact is `false`)
- `gather_facts` — `gather_hardware()` now returns a `cpu` field, parsed from the
  `CPU Model` line of `clish -c 'show asset system'` output
- `gather_facts` — `gather_hotfixes()` now captures `BUNDLE_*` prefixed lines in addition to
  `HOTFIX_*` lines, so the `[CPUpdates]` product section (previously empty) is now populated

### Changed

- `gather_facts` — `hotfixes` return value restructured: each entry in a product's `hotfixes`
  list is now a `{"name": ..., "take": ...}` dict instead of a bare string, so one-off
  hotfixes layered on top of a Jumbo HFA (e.g. `HOTFIX_R82_JHF_T103_HF2_MAIN`) report their
  own `take` number instead of having it silently discarded
- `gather_facts` — `hotfixes` return value now wraps per-product detail under a `products`
  key, with a new top-level `jhf` key holding the Jumbo HFA take number sourced from the
  `FW1` product only. Per-product `jhf` is no longer set on every product line that happens
  to carry a `JUMBO_HF_MAIN` entry — it is now scoped to `FW1` exclusively
  (e.g. `chkp_facts.hotfixes.jhf` instead of `chkp_facts.hotfixes.FW1.jhf`)
- `gather_facts` — `gather_hardware()` platform detection now checks both the `Platform`
  and `Model` fields from `show asset system` output (previously only checked `Platform`),
  fixing Check Point appliances misreported as `platform: unknown` when the vendor string
  appeared only in `Model`
- `gather_facts` — `gather_hardware()` `model` field now falls back to the raw `Platform`
  value when no explicit `Model` field is present in the clish output (e.g. HP ProLiant
  hosts, which report the model string in `Platform` rather than `Model`)
- `gather_facts` — `gather_cpda()` `build` field is now returned as an `int` instead of a
  `str`, matching long-standing downstream usage (`build | int`); falls back to `0` if the
  value is non-numeric

 ### Fixed

- `gather_facts` — `gather_hardware()` no longer crashes with `UnboundLocalError` when
  `Platform`, `Model`, or `CPU Model` fields are absent from `show asset system` output
- `gather_facts` — `gather_hotfixes()` no longer drops the `Take:` number on hotfix lines
  that don't match `JUMBO_HF_MAIN` or `JHF_COMP` (e.g. one-off hotfixes layered on top of
  a Jumbo HFA)

### Breaking Changes

- `hotfixes.<product>.hotfixes` changed from flat list to list-of-dicts
- `hotfixes.<product>.jhf` removed and moved to top-level `hotfixes.jhf` key
- `cpda.build` changed from `str` to `int`; `0` means parsing error

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

