# Security review

For the administrator who decides whether SolidSeas may run on a managed PC or
server. It is written to the `desktop-app-security-review` pattern: the
findings come first, with a severity and a status, then the evidence. Every
claim is marked **verified** (by a test in the suite, or by a check run during
this review) or **by inspection** (read in the code), and section 1.7 lists the
commands that repeat each check.

| Section | Covers | State |
|---|---|---|
| 1 | `solidseas serve`, the local REST service (Phase 1) | Reviewed on 2026-10-01, SolidSeas 0.2.0, Windows 10; a second review the same day added findings 15 to 22, and the fixes it asked for are in 0.2.1; 0.2.9 lets clients check the service before they send a token (finding 15), and 0.2.10 corrects how a client must use that check and how the check answers for a name with no token; 0.2.25 adds `/v1/bom` (provisional), which reads the component files it resolves in a worker, within the roots, and is in the route mix of `test_the_server_process_never_opens_a_document` and `test_hostile_files_get_strict_answers_in_time`; a review of its code paths in 0.2.114 found finding 26, fixed: the server resolves with lookups outside the roots off, the worker opens a component only within one of its roots (any other folder is refused there too), under the service's size and hard-link rules, and a BOM is bounded by 10,000 instances, 2,000 files opened, 60 s of reading, the route's 120 s deadline and an 8 MiB answer; 0.2.31 adds the catalog, off unless the service starts with `--catalog` (provisional): a thread that scans the roots at start and every `--catalog-rescan` seconds, with two workers of its own below normal priority under the service's memory, size and hard-link limits, into a SQLite catalog in the cache folder of the service's account (1.6), and the routes `/v1/catalog`, `/v1/where-used` and `/v1/search`, which answer from a read-only connection within a 5 s deadline that holds for the SQL and for where-used's own walk, under a 1 MiB cap, with root ids and relative paths only; `test_hostile_files_get_strict_answers_in_time` runs with the catalog on and asks where-used of every hostile file, and its walk up is bounded however a crafted tree branches (`test_the_where_used_walk_is_bounded`); it has not had a review of its own; 0.2.47 adds `--formats` (provisional, section 1.9), off unless the service starts with it: `/v1/document`, `/v1/properties`, `/v1/preview` and `/v1/list` then read the other 3D formats SolidSeas reads, in the workers, under the service's limits and the readers' own; the final code review of that work found findings 23 to 25, all fixed before release, and `test_hostile_model_files_get_strict_answers_in_time` puts every route through hostile model files; it has not had a security review of its own |
| 2 | The desktop app: the AI connector, the script runner, the SOLIDWORKS bridge and the machine policy (Phase 5) | Reviewed on 2026-10-23 at SolidSeas 0.2.489, by reading the code and running the tests named on Linux; the tests marked Windows and those that need SOLIDWORKS did not run for this review. Findings 34 to 58 |
| 3 | The OCCT backend's helper, the extension packages, and lookups outside the opened folder | Reviewed on 2026-10-23 at SolidSeas 0.2.489, as section 2. Findings 59 to 67 |

Apart from `solidseas serve`, the library and the command line open no socket.
They start no process other than their own worker processes, except the OCCT
backend's helper (section 3) when that backend is available and a file needs
it (an IGES or BREP file opened, `solidseas convert`, `export --check`), and
the SOLIDWORKS bridge for `python -m solidseas.swapi` (section 2). Section 1.3
shows the evidence, because the service is built on them.

## 1. `solidseas serve`

`solidseas serve` answers HTTP GET and HEAD requests about the SOLIDWORKS
documents in folders an administrator names (the roots), for systems such as
an ERP or an online store. Started with `--formats` (provisional), it also
answers `/v1/document`, `/v1/properties`, `/v1/preview` and `/v1/list` for the
other 3D formats SolidSeas reads; section 1.9 reviews what that adds. It reads documents and never writes, renames or
deletes anything under a root. `docs/API.md` section 8 is its reference, and
8.14 shows how to run it as a background service.

### 1.1 Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | The service speaks plain HTTP. On loopback that is the norm; bound to another address (`--allow-remote`), tokens and document data cross the network unencrypted. | Medium | Condition: bind beyond loopback only inside a private container network (API 8.2) |
| 2 | A token reads every document under every root, including path reports, which name accounts, servers and project folders. | Medium | Needs a decision: serve only folders every client may read in full, with one token per client |
| 3 | The Linux-only code has not run yet: the `RLIMIT_AS` memory cap, the parent-death signal, the `O_NOFOLLOW` opens in the worker, and the token file's mode and owner checks. This review ran on Windows. | Medium | Open: confirm on the first Linux CI run before a Linux deployment |
| 4 | The service is Python code installed with pip. Whoever can write to that Python environment (the interpreter, its DLLs, the standard library, SolidSeas itself) can change what the service runs, as the service's account. Nothing is code signed. | Medium | Fix by install location: under `C:\Program Files`, or root-owned on Linux |
| 5 | Worker processes cap each document's time and memory but are not a sandbox: a parser bug that ran code would run as the service's account, with its file and network access. | Low | Mitigated (section 1.5), accepted |
| 6 | The token file is plain text, protected by its access list or mode, not encrypted. | Low | Accepted: any process of the service's account can read it either way; encrypting it in that account's scope would not change that |
| 7 | The start-up check read the token file's own access list or mode, not its folder's, and on Windows not the file's owner, while it trusted OWNER RIGHTS whoever the owner was. Any user can create `C:\ProgramData\SolidSeas` before the administrator does and keep the right to change it as its owner; while the service was stopped, that account could put a token file of its own there, owned by it and granting OWNER RIGHTS and the service, and the check accepted it. | Medium | Fixed in 0.2.1: the check now refuses a file or folder owned by anyone but the service's account, SYSTEM or Administrators (`not_owner`) and a folder another account may add to, delete from or re-permission (`folder_writable`), on Windows and on Linux and macOS; the ProgramData recipe (API 8.14) refuses a folder that exists already and sets its owner. Verified: `test_a_token_file_owned_by_another_account_refuses_the_start`, `test_a_token_file_in_a_folder_others_control_refuses_the_start` |
| 8 | The limit on failed tokens counts per peer address. On loopback every local program is 127.0.0.1, so one that keeps sending wrong tokens makes the others wait (429 for 60 s). | Low | Accepted: a local denial of service only. The limit does not protect tokens from guessing: `/v1/identity` answers anyone, without a token and without counting a failure, with an HMAC under a client's token over a message the asker knows, so guesses at a token can be tested offline, without limit. A token from `secrets.token_urlsafe(32)` (256 bits, as the service makes the first one) cannot be guessed that way; a hand-written one can be weak, and the start-up check, which accepts any 32 to 128 URL-safe characters, cannot tell. API 8.3 and the token file's header therefore require every token to be generated |
| 9 | The one dependency, `olefile`, is pinned by minimum version, not by hash. | Low | Needs a decision: install from a hash-locked requirements file |
| 10 | There are no automatic updates. | Low | Deployment responsibility: a fix means reinstalling the package |
| 11 | Windows' no-recall open flag, which keeps a cloud file from downloading when opened, was checked on local NTFS only, not on deduplicated or cloud-synced volumes. Placeholders are refused by their attributes before any open. | Low | Open: check on a OneDrive folder before serving one |
| 12 | A path given as an 8.3 short name is not found (404), but the test skips on this machine's volume, which makes no short names. | Low | By inspection only |
| 13 | Started as LOCAL SERVICE or NETWORK SERVICE, the service refused its own token file: Windows writes those accounts as `LS` and `NS` in an access list, and the check compared text. | - | Fixed during this review |
| 14 | Under `pythonw.exe`, as a Scheduled Task without a window uses, the service exited at start: it had nowhere to write its ready line. | - | Fixed during this review |
| 15 | Clients could not tell whether they were talking to the real service. Whenever it is stopped (between restarts, before it starts at boot, after its supervisor gives up), any process of any account can listen on 127.0.0.1:8765 and receive the `Authorization` header a client sends, a token that reads every document under every root. The exclusive bind (API 8.2) helps only while the service runs, and only on its own address: with the service on 127.0.0.1:8765, another program can listen on [::1]:8765, where a client that calls `localhost` may connect (verified on Windows 10 by `test_a_forwarder_on_another_address_of_the_same_port_is_refused`). | Medium | Fixed in 0.2.9 for clients that check: `GET /v1/identity` answers a client's fresh nonce with an HMAC-SHA256, under that client's token, of the nonce and of the address and port the connection reached, so a client checks the service before its token leaves it. A guessed proof, one collected earlier, and one forwarded from the real service to another address or port all fail the check (API 8.16). A check covers only the connection it was made on, so a client that keeps connections open and picks one per request is covered only when it checks and sends its token on the same new connection. In 0.2.9 the documented TypeScript client checked with `fetch`, whose pool could reuse a connection another program had accepted while the service was stopped: once the service ran, that program could forward the check to it and pass it (shown on Windows 10 with Node 24 by a later review, and by `test_the_typescript_client_never_reuses_a_connection_from_before_the_service_ran`, which fails against the 0.2.9 client). From 0.2.10 the TypeScript client checks and sends each request on one new connection that it never reopens, as the Python client does, and the PowerShell example opens a new connection for each call. A client that does not check, or that checks on one pooled connection and sends on another, stays exposed, so the condition stays: on a machine other accounts use, keep the service supervised and have clients check, send on the checked connection, and fail closed. Verified: `test_the_documented_python_client_sends_its_token_only_to_the_service`, `test_a_checked_connection_never_reconnects_by_itself`, `test_a_program_that_takes_the_port_of_a_stopped_service_gets_no_token`, `test_a_forwarder_on_another_address_of_the_same_port_is_refused`, `test_the_documented_typescript_client_sends_its_token_only_to_the_service`, `test_the_typescript_client_never_opens_a_connection_it_did_not_check`, `test_the_documented_store_page_sends_its_token_only_to_the_service`, `test_the_typescript_client_never_reuses_a_connection_from_before_the_service_ran` |
| 16 | Any local process could deny service without a token by holding the 64 connection slots: an idle connection lived for the 10 s head deadline, each refused connection held up the ones behind it for a second, and a connection cut at the deadline left no trace in the log. | Low | Fixed in 0.2.1, partly: a new connection must send its first byte within 5 s (`idle_timeout`), a refused one is drained for at most 0.1 s, and a connection closed because no head arrived in time is logged with its peer and rule. Holding the slots by reconnecting stays possible: a local denial of service only, as finding 8 |
| 17 | The header limit (16 KiB in all) was checked only after Python's parser had read up to 100 lines of 64 KiB each, before any token check: 60 unauthenticated local clients took the service process from 21 MiB to 370 MiB. | Low | Fixed in 0.2.1: header bytes past the limit are never read, and the request answers 431. Verified: `test_an_oversized_head_is_not_read_past_its_limit` |
| 18 | The worker pool accepted answers up to 64 MiB although routes cap theirs at 1 to 16 MiB, and the uncapped server process read and parsed each before refusing it: a 1.4 MB crafted assembly made each references request cost hundreds of MiB there. | Low | Fixed in 0.2.1: each call carries its route's cap plus 64 KiB, and the worker refuses a longer answer before sending it. Verified: `test_an_answer_over_its_cap_never_reaches_the_server_process` |
| 19 | Only the last component of a located path was checked for a link: a folder indexed at start and later replaced by a symbolic link to a share made the service's `lstat` (and the worker's open) go through it, so Windows connected over SMB as the service's account. Needs write access in a root and the right to create symbolic links. | Low | Fixed in 0.2.1: every component is checked from the root down before the next is used, in the service and in the worker's open. Verified: `test_an_indexed_folder_swapped_for_a_link_is_never_entered`, `test_the_workers_open_refuses_a_link_before_opening_through_it` |
| 20 | After three failed attempts to replace a worker, its slot was lost for good, with nothing logged and `/v1/health` still ok; with every slot lost, every document route answered 504 until a restart. | Low | Fixed in 0.2.1: a replacement is retried, with a wait growing to 30 s, for as long as the service runs, and only after the old worker has ended; pool events are logged, and health answers 503 while no worker runs. Verified: `test_a_lost_worker_is_replaced_even_after_failed_starts`, `test_health_fails_while_no_worker_is_running` |
| 21 | A request line without an HTTP version was answered as HTTP/0.9, a bare body without a status line or any security header, and a method the service did not know answered 405 before the Host check. | Low | Fixed in 0.2.1. Verified: `test_every_answer_has_a_status_line_and_the_security_headers`, `test_the_host_check_comes_before_the_method_check` |
| 22 | REST resolution searched the folder indexes built at start, so a project moved while the service ran was resolved to its old place with high confidence until a restart, and a root that failed indexing was left out without a word. A correctness finding with a security edge: a stale answer can send someone the wrong file. | - | Fixed in 0.2.1: each resolution walks the roots again, and a root that cannot be walked is reported (`root_unavailable`). Verified: `test_resolution_sees_a_project_moved_after_the_start` |
| 23 | With `--formats`, the files a model file names (a glTF buffer, an OBJ material library, an Alibre component) were opened without the service's hard-link refusal or its file-size limit: a hard link inside a root let a document draw a preview from a file outside it, and an Alibre assembly's preview drew a hard-linked component that the service refused to serve itself. | Medium | Fixed before release: a document carries the rules it was opened with to every file it names (API 3.20.1). Verified: `test_hostile_model_files_get_strict_answers_in_time` (hard-linked buffer, library and component, and a buffer through a junction), `test_siblings_keep_the_rules_the_document_was_opened_with`, `test_components_keep_the_rules_the_assembly_was_opened_with` |
| 24 | With `--formats`, `/v1/document` gave where a model file's buffers and material libraries were found as absolute paths on the service's machine, found with an `lstat` that went through a junction in the middle of the path (and called such a file found while a read refused it). | Medium | Fixed before release: the path is relative to the document's folder, each component is read with `lstat` only after the ones above it passed, a link anywhere is `refused`, and the service sends any path that is not relative as null. Verified: `test_hostile_model_files_get_strict_answers_in_time` (no host path in any body), `test_sibling_resolution_is_relative_and_never_goes_through_a_link` |
| 25 | With `--formats`, crafted model files answered 500 `internal` (a 3MF transform of NaN or infinity, an XML encoding Python lacks) or 501 `not_implemented` (a zip directory naming an unknown zip version), and a coordinate of 1e300 made exports fail with an overflow. Each cost one answer; none stopped the service. | Low | Fixed before release: each is a reader's own error or a warning. Verified: `test_hostile_model_files_get_strict_answers_in_time`, which also checks that every answer is strict JSON, a PNG or one of the expected error statuses within its deadline |
| 26 | `/v1/bom` with `type=indented` worked out each row's quantity by looking through every instance of its parent again, so an assembly whose sub-assembly instances each list different components (a crafted or damaged tree; SOLIDWORKS lists one model per file and configuration) kept a worker busy up to the route's deadline. | Low | Fixed in 0.2.112: planning counts each instance once, so it is linear in the tree the instance limit bounds. Verified: `test_an_indented_plan_counts_each_instance_once_however_its_tree_is_crafted` |
| 27 | With `--formats`, the zip pre-check read a ZIP64 end record only when the classic end record held sentinels, while Python's `zipfile` takes one whenever a locator stands before the end record: a crafted 3MF made a worker build an object for every entry of a directory up to the file's size (a 15.6 MB package peaked at 157.5 MB before it was refused). | Low (a worker's memory cap contained it) | Found by a later review of the readers; fixed after 0.2.406: the end records are read as `zipfile` reads them, and the directory `zipfile` reads is refused past `zip_directory_bytes` and has its entries counted against `zip_members` before one is built. Verified: `test_a_zip64_end_record_is_read_as_python_reads_it`, `test_the_directory_zipfile_reads_is_bounded_and_counted_before_it_is_built` |
| 28 | With `--formats`, a glTF accessor without a buffer view was filled with zeros before its sparse block's views were checked (a 552-byte file peaked at 495 MB for 20 million positions, about 1.4 GB at the default bound), a strided view was copied as one object an element, and up to 1,000 buffers could each name the same 512 MiB file. | Low (a worker's memory cap contained it) | Found by a later review of the readers; fixed after 0.2.406: the sparse block is read and checked first and the zeros are bounded by its bytes, a strided view is copied a byte column at a time, and `sibling_total_bytes` bounds every read of a file a document names. Verified: `test_a_sparse_block_is_read_and_checked_before_any_zero_is_made`, `test_buffers_beside_the_file_are_bounded_in_total` |
| 29 | `serve --formats stl` read a `.stl` that holds a STEP, 3MF or glTF file with those formats' readers: the workers opened model files without the service's formats, and detection lets the content win. | Medium | Found by a later review of the readers; fixed after 0.2.406: a worker reads a file only as one of the service's formats, and any other content answers 422 `format_not_supported`, rule `format_not_enabled`. Verified: `test_a_file_is_read_only_as_a_format_the_service_reads` |
| 30 | Model files were read with the library's default bounds, which allow a scene of several gigabytes (20 million triangles of a binary STL's scene is about 3.2 GB), and a `MemoryError` outside a worker passed through as such. | Low (a worker's memory cap answered `limit_exceeded`) | Found by a later review of the readers; fixed after 0.2.406: the service reads model files within `SERVE_LIMITS` (10 million triangles, 30 million vertices, 512 MiB of named files; API 8.8), inside the 2 GiB cap, and a reader turns `MemoryError` into `limit_exceeded` (`detail.limit` `memory`) everywhere. Verified: `test_the_jobs_read_only_the_formats_and_within_the_limits_the_worker_has`, `test_running_out_of_memory_is_a_limit_error` |
| 31 | With `--formats`, a model file in a root served without its subfolders could read the files it names (a glTF buffer, an OBJ material library, an Alibre component) from subfolders the service does not serve, and drew them into its preview; an Alibre assembly's component search, which every request reading it makes again, examined up to 50,000 entries and 5,000 candidates. | Low | Found by a later review of the readers; fixed after 0.2.406: such a root's documents read named files from their own folder only (a buffer or library below is `refused`, a preview that needs one answers 403 `path_refused`, rule `subfolder`), and `SERVE_LIMITS` bounds the component search to 5,000 entries, 500 candidates and 5 s. Verified: `test_a_root_served_without_subfolders_reads_no_file_below_a_documents_folder` |
| 32 | `/v1/identity` answered a name with no token under a stand-in key derived from all the tokens, so an edit of the token file changed every unknown name's proof while each kept name kept its own: someone who asked about a list of names before and after an edit could tell which of them hold a token. | Low | Fixed: the stand-in is keyed by the service's identity key, a secret of its own in a file beside the token file, made on the first start that finds none and checked on every start by the token file's rules (API 8.3); an edit now changes only the proofs of the names it adds, deletes or gives a new token. Verified: `test_an_unknown_names_proof_survives_an_edit_of_the_token_file` (with the stand-in made from the tokens as its control), `test_the_service_keeps_an_unknown_names_proof_across_an_edit_of_its_tokens`, `test_the_cli_keeps_its_identity_key_beside_the_token_file`, `test_a_bad_identity_key_file_refuses_the_start`, `test_an_identity_key_file_others_can_read_refuses_the_start` |
| 33 | Three statements of this section had stopped being true: that nothing in `src/solidseas` uses `subprocess` (the helper runner, `solidseas/helpers.py`, always has), that the service starts no process but its workers (since 0.2.430 a worker may start the OCCT helper, section 3), and that the search in 1.7 finds nothing. | - | Fixed during this review: 1.2, 1.4, 1.5, 1.6 and 1.7 say what runs, and the search says what it finds |

### 1.2 What the service is

- One Python process (the server) and a fixed number of worker processes, one
  per CPU and at most 4 by default. Standard library only, plus `olefile` for
  legacy documents. Nothing is downloaded, compiled or loaded at run time.
- With `--formats` naming `iges` or `occt_brep` (or `all`), and the OCCT
  backend available when the service starts, each worker may start one helper
  process: `solidseas-occt.exe` from the OCCT extension's package in the service
  account's `%LOCALAPPDATA%\SolidSeas\extensions\occt`, or, from a source
  checkout, the Python `SOLIDSEAS_OCCT_HELPER_PYTHON` names. Open CASCADE, which
  is C++, reads the geometry there, from a copy of the file in the account's
  temporary folder. Section 3 reviews it; otherwise the workers start nothing.
- The server process checks each request and answers it; it never opens a CAD
  file. Every document is read in a worker, under a deadline and a memory cap.
  Verified: `test_the_server_process_never_opens_a_document` records every
  document opened in the server process while every route is exercised, and
  finds none.
- It runs as whichever account starts it, with that account's read access to
  the roots. API 8.14 recommends the user's own account on a workstation and
  LOCAL SERVICE, granted read access to the roots, on a shared machine.

### 1.3 Network surface

The complete set of network activity is one listening TCP socket, on
127.0.0.1 port 8765 unless configured otherwise, answering HTTP. Nothing else:
no outbound connection, no name lookup, no update or licence check, no
telemetry or crash reporting. The worker processes open no sockets: they talk
to the server over anonymous pipes.

| Claim | Evidence |
|---|---|
| One listening socket, on loopback by default, and only while the service runs: a stopped service's port can be taken by any local account, which a client that checks `/v1/identity` first detects (finding 15) | Verified. Tests: `test_the_default_bind_is_loopback`, `test_localhost_means_127_0_0_1_and_loopback_needs_nothing_more`. This review: with the service running and requests in flight, `Get-NetTCPConnection` showed one `Listen` on 127.0.0.1 and the clients' connections for the service process, and `Get-NetUDPEndpoint` nothing |
| Without a token the service answers two routes and reads no document for either: `/v1/health` (`{"status": "ok"}`) and `/v1/identity` (a proof under the asking client's token, API 8.16). The proof does not reveal the token, and a name with no token gets a proof that looks the same and, like a real name's, stays the same across restarts and across edits of the token file (its stand-in key comes from the service's identity key, a secret of its own kept beside the token file; a key made new at each start would change it, and one derived from the tokens changed with every edit, either of which told the two apart, finding 32). Neither route counts as a failed attempt, so the proof lets guesses at a token be tested offline: tokens must be generated (finding 8) | Verified. Tests: `test_every_route_but_health_and_identity_needs_the_token`, `test_the_service_proves_it_holds_each_clients_token`, `test_an_unknown_name_gets_a_proof_that_looks_like_any_other`, `test_an_unknown_names_proof_survives_a_restart_as_a_real_names_does`, `test_an_unknown_names_proof_survives_an_edit_of_the_token_file`, `test_the_service_keeps_an_unknown_names_proof_across_an_edit_of_its_tokens`, `test_the_route_needs_no_token_and_counts_no_failure` |
| `--identity-address` (off unless given) lets a client behind a port mapping check the service: the proof covers a named IP address and port only for a request whose `Host` header names it, a name never counts, and an address that is not one (a host name, no port, `0.0.0.0`, multicast) refuses the start. Whoever holds a named address while the service runs can forward a check, so API 8.16 says to name only an address the mapping holds whenever the service runs | Verified. Tests: `test_an_identity_address_lets_a_client_behind_a_port_mapping_check_the_service` (with the check failing closed through the mapping without it as its control), `test_the_host_header_chooses_the_covered_address_only_among_those_named`, `test_a_relay_elsewhere_cannot_borrow_a_named_address`, `test_an_identity_address_that_is_not_one_is_refused` |
| Any other address is refused unless `--allow-remote` and an allowed host name are given, before anything listens | Verified. Tests: `test_any_other_bind_needs_allow_remote_and_an_allowed_host`, `test_the_cli_refuses_a_remote_bind_before_anything_listens` |
| The service process connects to nothing and looks up no name | Verified. The service's test modules run under a guard that fails any `connect` or `getaddrinfo` to a host other than loopback, and fails the module afterwards if anything tried; `test_the_outbound_guard_is_on` is its control |
| It does not look up its own host name, as Python's `HTTPServer` does by default | By inspection: `server_bind` is overridden without that lookup |
| Only one module uses the network | Verified. `test_only_the_service_module_touches_the_network` reads every module's code and finds network imports in `serve/server.py` alone |
| Worker processes open no sockets | Verified, this review: `Get-NetTCPConnection` and `Get-NetUDPEndpoint` for both workers of a running service showed nothing |
| A path stored inside a document (a UNC share, a mapped network drive) is never touched, so no document can make the service connect to a server it names | Verified. `tests/test_resolve_safety.py` traps every filesystem call for planted UNC and network-drive paths, with a check that the trap works |
| A folder under a root replaced by a link (to a share, for example) is refused before any path through it reaches the operating system | Verified: `test_an_indexed_folder_swapped_for_a_link_is_never_entered` records every `lstat`, `stat` and folder listing the service makes and finds none through the link; `test_the_workers_open_refuses_a_link_before_opening_through_it` does the same for the worker's open. Creating such a link needs write access in the root and the right to create symbolic links |
| Workers end with the service | Verified, this review: stopping the service's process ended its workers. On Windows they share a Job Object with kill-on-close; on Linux each asks for `SIGKILL` when its parent dies (by inspection, finding 3). An OCCT helper (1.2) runs in a Job Object of its own, nested in the pool's, whose handle its worker holds, so it ends with its worker and with the pool; on Linux it asks for `SIGKILL` when its worker dies. By inspection only (section 3) |

What will show up anyway, and is not the service's own connection: when a root
is a folder on a file share, Windows' or Linux's SMB client connects to that
server, as the service's account, to read the files. Only roots the
administrator configures are read that way.

### 1.4 What runs

- No `os.system`, `shell=True`, `eval`, `exec`, `pickle` or `marshal` anywhere
  in `src/solidseas`, and `subprocess` only in the helper runner
  (`solidseas/helpers.py`, from an argument list, never through a shell) and the
  SOLIDWORKS bridge's client. The service reaches the helper runner only through
  the OCCT backend, under the condition in 1.2. Verified by the grep in 1.7.
- Worker processes are started with the `spawn` method, running the same
  interpreter. What a job may do comes from a fixed table in `solidseas.jobs`:
  nothing in a request, a document or a configuration adds a job. By
  inspection.
- A worker's answer comes back as JSON read with a length limit, plus one raw
  frame for an image. It is never unpickled, so a compromised parser cannot
  send back code for the server to run. Verified:
  `test_worker_results_are_never_unpickled` reads the module's source.
- Native calls are Windows API calls through `ctypes`, with declared types, to
  `kernel32` and `advapi32` (opening files, Job Objects, access lists, drive
  types), and on Linux `prctl` in libc. By inspection.

### 1.5 Untrusted input

Two inputs come from outside: requests, and the documents under the roots
(anyone who can save a file into a root can hand the service a crafted one,
or put a link where a folder was, finding 19).

- **Requests.** Host, Origin and Fetch Metadata are checked before routing, so
  a web page in a browser on the same machine cannot use the service (DNS
  rebinding included); there is no CORS unless the service is started with
  `--allow-origin`, which names exact origins whose pages may call it with a
  token (API 8.4; verified: `test_an_allowed_origin_may_call_the_service_and_read_its_answers`,
  `test_every_other_origin_is_still_refused`,
  `test_a_preflight_from_an_allowed_origin_is_answered`,
  `test_any_other_preflight_is_refused`). Each route has a parameter allowlist;
  URL, header and body limits apply, header bytes past the limit are never read
  (finding 17), and a slow sender is cut off and logged. Verified:
  `test_a_wrong_host_is_refused`, `test_cross_site_browser_requests_are_refused`,
  `test_no_response_carries_cors_headers`, `test_the_query_allowlist` and its
  control, `test_a_long_url_answers_414`,
  `test_too_many_or_too_large_headers_answer_431`,
  `test_a_slow_sender_is_cut_off_while_others_are_served`.
- **Settings.** A configuration file (`--config`, API 8.17) is read failing
  closed: an unknown key or a wrong type refuses the start, and so does a file
  or folder that another account may change or owns, since the file names the
  roots, the address and the origins. Verified: `tests/test_serve_config.py`
  (the Windows access-list cases run on Windows).
- **Paths in requests** are checked as text and then looked up in the root's
  folder index: no text from a request is ever joined into a path. Links,
  junctions, mount points, hard links, alternate data streams, device names and
  cloud placeholders are refused. Verified: `test_a_refused_path_never_reaches_the_disk`
  (a table of refused paths whose size is asserted),
  `test_encoded_traversal_is_decoded_once_and_refused`,
  `test_a_link_inside_the_root_leads_nowhere` with its control,
  `test_a_hard_link_is_refused`, `test_workers_only_ever_open_paths_inside_the_root`.
- **Documents** are parsed in pure Python (`olefile` for legacy files, `zlib`
  and the standard XML parser). An XML stream that declares a DOCTYPE or an
  entity is refused before parsing, decompression has a budget per document,
  and legacy sector chains are checked before they are walked. Verified:
  `tests/test_hardening.py`, and `test_hostile_files_get_strict_answers_in_time`,
  which puts every crafted file of the hostile-file tests in a root and checks
  that every route answers strict JSON within its deadline. With `--formats`,
  the other formats' parsers run in the workers too (section 1.9), and IGES and
  BREP geometry in Open CASCADE, in the worker's helper (1.2, section 3): a crash
  there ends the helper and costs one answer, and a hang ends at the worker's
  deadline, which ends the helper with it.
- **Hangs, crashes and memory bombs** cost one answer: a worker that misses its
  deadline is killed and replaced, a crash answers `worker_crashed`, and an
  allocation over the cap fails inside the worker. Verified on Windows:
  `test_a_slow_crashing_or_greedy_file_is_contained` and `tests/test_workers.py`.
- **What goes back out.** A preview is served only after the service checked it
  is a PNG, or built the BMP itself, and a 3D model only after it checked the
  GLB's frame (section 1.10); no route serves HTML, SVG or XML (the reference
  viewer's page, with `--viewer`, is the one HTML answer, section 1.10); every
  response carries `nosniff`, a `default-src 'none'` CSP and
  `Cross-Origin-Resource-Policy: same-origin`. Error answers never carry the
  reader's own message, which can hold a path, and the log never holds a path,
  a query, a token or anything read from a file. Verified:
  `test_only_a_checked_image_is_served_as_a_preview`,
  `test_every_response_carries_the_security_headers`,
  `test_errors_never_carry_the_readers_message`, and
  `test_nothing_planted_reaches_the_logs`, which also checks that the planted
  values do reach the path report, so it cannot pass by checking nothing.

### 1.6 What it stores

| What | Where | Contents | Protection |
|---|---|---|---|
| The catalog, only with `--catalog` | `%LOCALAPPDATA%\SolidSeas\catalogs\<name>\` of the service's account on Windows (`catalog.sqlite`, `previews.sqlite`, their write-ahead logs and `catalog.lock`); `$XDG_CACHE_HOME/solidseas/catalogs/<name>/`, by default `~/.cache/solidseas/...`, elsewhere | Every document's name and path below its root, the roots' own paths, every custom and configuration property (part numbers, descriptions, customer names, prices if a property holds them), summary fields such as author and last saved by, the stored paths of references (absolute paths from other machines, with account and server names), preview images, hashes, and 90 days of change events, names of removed files included | Windows: the profile's own access list (the account, SYSTEM, Administrators); Linux and macOS: folders made 0700 without following a link. Nothing is ever written through a link or into a file that is not a plain one, and a database that is not a catalog is refused before anything is written. Never on a network location (Windows), never under a root: a cache folder inside a root stops the service from starting. A catalog folder another account owns, or inside a folder everyone may write to without the sticky bit, is refused (Linux and macOS), and a catalog holding a view or a trigger is never opened, every connection running with SQLite's `trusted_schema` off. The routes serve it as root ids and relative paths only, the log holds counts only, and `solidseas clear-index --catalog NAME` (or deleting the folder) removes it. Verified: `test_the_service_answers_from_its_catalog`, `test_the_in_project_catalog_never_writes_through_a_planted_link`, `test_a_scan_writes_nothing_into_the_scanned_folder`, `test_the_catalog_is_never_kept_under_a_root`, `test_a_catalog_holding_a_view_or_a_trigger_is_never_opened`, `test_a_catalog_folder_another_account_could_swap_is_refused` |
| The token file | `%LOCALAPPDATA%\SolidSeas\serve-tokens` on Windows; `$XDG_CONFIG_HOME/solidseas/serve-tokens`, by default `~/.config/solidseas/serve-tokens`, elsewhere; or the `--token-file` path, whose folder must exist | One `name:token` line per client; comments | Created on the first start, never overwritten. Windows: a protected access list granting the account alone; Linux and macOS: mode 0600, created exclusively without following a link (the default folder is created 0700). Refused at every start when an account other than the service's own, SYSTEM, Administrators and OWNER RIGHTS can read it (Windows), or when it has a group or other mode bit (Linux, macOS); when the file or its folder is owned by another account; and when another account may add to, delete from or re-permission the folder. Verified on Windows: `test_the_token_file_is_created_for_the_user_alone`, `test_a_token_file_others_can_read_refuses_the_start`, `test_a_service_account_recognises_its_own_token_file`, `test_a_token_file_owned_by_another_account_refuses_the_start`, `test_a_token_file_in_a_folder_others_control_refuses_the_start`; the POSIX folder check has its own test, which runs on Linux |
| The identity key file | Beside the token file, under its name with `.identity` added, or the `--identity-key-file` path, whose folder must exist | One line: the service's own secret, which keys `/v1/identity`'s answers for names without a token (API 8.16); never printed or logged | As the token file: created on the first start that finds none, never overwritten, with a protected access list (Windows) or mode 0600 (Linux, macOS), and refused at every start by the same rules (`identity_key_refused`). Verified: `test_the_identity_key_file_is_made_beside_the_token_file_for_the_user_alone`, `test_an_identity_key_file_others_can_read_refuses_the_start`, `test_an_identity_key_the_service_cannot_create_refuses_the_start` (POSIX) |

Nothing else. The service writes no log file (log lines go to standard error,
for the service manager), keeps no cache or database but the catalog when it
is asked for one, writes nothing under a root, and writes nothing to the
registry. With the OCCT helper (1.2), each IGES or BREP file read is copied to
a folder of its own in the service account's temporary folder for the helper,
and removed after it, except when the worker is killed at its deadline
(finding 59); a worker keeps converted files in memory, at most 256 MiB. It never prints or logs a token.
No credentials of any kind are requested, used or stored besides its own
bearer tokens and identity key, and it never authenticates to anything.

### 1.7 Repeating the checks

From a checkout, with the development dependencies installed:

```text
python -m pytest -q tests/test_serve_security.py tests/test_serve_identity.py tests/test_serve.py tests/test_serve_config.py tests/test_serve_viewer.py tests/test_workers.py tests/test_resolve_safety.py tests/test_hardening.py tests/test_formats_core.py tests/test_formats_mesh_hostile.py tests/test_formats_step_hostile.py tests/test_formats_alibre_hostile.py tests/test_occt_backend.py
```

Expected: every test passes; on Windows the POSIX-only tests skip, and on
Linux the Windows-only ones (access lists, Job Objects, junctions).

```text
git grep -nE "import socket|http\.(client|server)|urllib\.request|import (requests|httpx)" -- src/solidseas ":!src/solidseas/ai"
```

Expected: `src/solidseas/serve/server.py` only (`import http.client`, whose
`http.client.LineTooLong` it raises for a request head past its limit and
names in a docstring, `import socket`, `from http.server import ...`, and a
local `import socketserver`). The AI connector, `src/solidseas/ai`, has its own
outbound HTTP client (`src/solidseas/ai/http.py`) for the desktop app; the
service never imports it, and section 2 reviews it.

```text
git grep -nE "\bsubprocess\b|os\.system|os\.popen|shell=True|import pickle|pickle\.loads|\bmarshal\b|(^|[^.[:alnum:]_])eval\(|(^|[^.[:alnum:]_])exec\(" -- "src/solidseas/*.py" ":!src/solidseas/swapi"
```

Expected: `src/solidseas/helpers.py` alone uses `subprocess` (its import, the
`Popen` from an argument list with its three pipes and its window flag, and two
`TimeoutExpired`), and `src/solidseas/nativewrite/solidcraft.py` defines a
method named `eval`, an arithmetic reader of its own over Python's syntax tree,
not the built-in. The search reads Python files only, so the vendored
three.js, whose minified code calls a regular expression's `exec`, is left out.
The SOLIDWORKS bridge's client, `src/solidseas/swapi`, starts
`SolidSeas.SwBridge.exe` through the helper runner, and the C# compiler that
builds it (`build.py`) with `subprocess`, from an argument list and never
through a shell; the service never imports it, and section 2 reviews the
bridge.

```text
git grep -n "getfqdn" -- src
```

Expected: one comment in `src/solidseas/serve/server.py`, where `server_bind`
leaves the lookup out.

While the service runs, on Windows:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Select-Object ProcessId, ParentProcessId, CommandLine
Get-NetTCPConnection -OwningProcess <pid>   # for each process of the service
Get-NetUDPEndpoint -OwningProcess <pid>
```

Expected: the process running `solidseas serve` (with a virtual environment,
a launcher process is its parent) has one `Listen` on 127.0.0.1:8765 and the
connections of its clients; its worker processes, whose parent it is, have
none; no process has a UDP endpoint. On Linux, `ss -ltnup` shows one listener,
on 127.0.0.1:8765. From another machine, `curl -m 5 http://<host>:8765/v1/health`
must fail.

### 1.8 Recommendation

Suitable to run on a managed Windows PC or server, bound to loopback, with
seven conditions:

1. Install Python and SolidSeas where only administrators can write, such as
   under `C:\Program Files` (finding 4).
2. Run it as the user on a workstation, or as LOCAL SERVICE with read access
   to the roots on a shared machine (API 8.14); never as SYSTEM or an
   administrator.
3. Serve only folders that every client may read in full, and give each client
   its own token (finding 2).
4. Keep the bind on loopback, or inside a private container network with no
   published port (finding 1).
5. On a machine other accounts use, keep the service supervised so its port is
   never free for long, have every client check the service with
   `/v1/identity` before it sends its token and send the token only on the
   connection it checked, or on a new connection per call where its HTTP
   library cannot do that (API 8.16), and have clients fail closed when that
   check fails or an answer is not the service's (finding 15).
6. Make every token with `secrets.token_urlsafe(32)` (API 8.3, finding 8).

7. Leave `iges` and `occt_brep` out of `--formats` (and name format ids rather
   than `all`) unless IGES or BREP must be served; where they are, run the
   service as an account of its own, so the helper's program and its copies
   sit in a profile only that account and administrators can change (section 3,
   findings 59 to 61).

On Linux, the same conditions apply, and only after the first Linux CI run
has passed (finding 3).

### 1.9 Other 3D formats (`--formats`)

The service reads other formats only when started with `--formats` (`all` or
format ids). What that adds, and what bounds it:

- **Parsers**, all pure Python and all in the workers: a zip reader
  (`SafeZip`: member count and directory size from the end records, a ZIP64
  record included as `zipfile` reads it, before `zipfile` reads the directory,
  and the directory it reads refused past its bound and counted before an entry
  is built (finding 27), encrypted members and unknown methods refused,
  each member inflated against its own bound, the document's total and a
  ratio), `expat` for XML (DOCTYPE, entity declarations and external entities
  refused before use; depth, attribute and text lengths bounded; an encoding
  Python lacks refused), a strict JSON parser (no NaN or Infinity, bounded size
  and depth), text readers for STL, OBJ, PLY, OFF and ISO 10303-21 (line and
  token lengths bounded), the compound-file reader the SOLIDWORKS reader uses
  (for Alibre Design), and the ACIS and Parasolid readers that feed the
  tessellator. Every count a file states is checked against its size or a
  limit before it is used, and every reader keeps a time bound (API 3.20.2).
- **Files a document names.** A glTF buffer and an OBJ material library are
  read only from inside the document's own folder: a reference that climbs
  out, is absolute, or names a drive, a UNC path, a scheme, a stream or a
  device is refused before anything is opened; the file is opened `within`
  that folder with no link, junction or placeholder on the way, under the
  document's own `refuse_hard_links` (always on in the service) and
  `max_file_bytes`, and counted against `siblings`, `sibling_bytes` and
  `sibling_total_bytes`, every read counted (finding 28); in a root served
  without its subfolders, from the document's own folder only (finding 31). A
  3MF's parts come only from its own package. An Alibre assembly's components
  are found by walking the assembly's own folder below the root (no link
  followed, no placeholder opened) and reading the identity stream of each
  Alibre file there; a file with a second name is no candidate, and the path
  the assembly stores is never opened (finding 23).
- **What comes back.** `model_summary` gives where a named file was found
  relative to the document's folder, or null (finding 24); placements and
  numbers that are not finite are null with a warning; a stored image is
  rewritten as a PNG SolidSeas made (API 3.20.1), and a rendered one is drawn
  by SolidSeas from the triangles.
- **Settings it honours**: `refuse_hard_links`, `max_file_bytes`, the worker
  deadlines and memory cap, each route's answer cap, the formats it was started
  with, which every worker enforces on a file's content and not only on its name
  (finding 29), and `SERVE_LIMITS`, the readers' `Limits` with a scene and the
  files a document names bounded to fit a worker (finding 30).
- **Verified**: `test_hostile_model_files_get_strict_answers_in_time` serves,
  with `formats="all"`, a zip bomb, a NaN transform, unknown XML encodings in
  3MF and AMF, a zip asking for an unknown version, a coordinate of 1e300, a
  damaged STL, a glTF buffer that climbs out, and a buffer, a material library
  and an Alibre component reached through a hard link (and, on Windows, a
  buffer through a junction). It checks that every route answers within its
  deadline with strict JSON, a PNG or an expected error, that no answer holds
  a path on the machine, and that nothing outside the root is drawn. The
  per-format hostile tests (`tests/test_formats_*_hostile.py`) bound each
  reader.

### 1.10 3D models and the reference viewer (`/v1/mesh`, `--viewer`)

Both are provisional and new; they have not had a review of their own. What
bounds them:

- **`/v1/mesh`** reads one document in a worker, as every route does, and opens
  no other file and lists no folder: a part's display mesh or its own bodies,
  an assembly's own stored meshes with no root to search and no file opened
  (`max_files` 0), the component files beside it included. Verified:
  `test_an_assembly_whose_meshes_are_in_its_part_files_opens_none_of_them`,
  `test_the_server_process_never_opens_a_document` (the route is in its mix),
  `test_hostile_files_get_strict_answers_in_time` (every hostile file through
  the route: a GLB with its frame checked, or strict JSON, in time).
- **What it sends** is a GLB the worker wrote: the server checks its frame
  (`is_glb`) and its 64 MiB cap before serving it as `model/gltf-binary`, with
  the service's headers, and a worker's answer that is not one answers 500
  (`test_only_a_checked_glb_is_served`). Its JSON holds instance and component
  names and file keys, never a path on the machine. A part is held to 1,000,000
  triangles and 256 MiB of display data; at most two answers are read at once,
  so their memory stays bounded (`test_mesh_answers_past_their_own_limit_answer_busy`).
- **The viewer is off by default**; without `--viewer`, `/` and `/viewer/`
  answer as unknown routes (`test_the_viewer_is_off_unless_asked_for`). On,
  its fixed set of files is read at start from the package, served without a
  token, with no parameter, under fixed content types, after the Host check
  (`test_the_viewer_serves_nothing_else`, `test_the_viewer_needs_the_host_check_and_takes_only_get`).
  Its page's policy allows scripts from the service and its import map by hash
  alone, and connections to the service alone (`test_the_page_is_served_with_its_own_policy`,
  `test_the_viewer_loads_nothing_from_anywhere_else`); its script writes no
  markup from what the service answers and keeps the token in memory, sent
  with `credentials: "omit"` and `redirect: "error"`
  (`test_the_viewer_never_builds_markup_from_what_the_service_says`). With the
  viewer on, an `Origin` that is the service's own passes the check of API 8.4,
  and no other (`test_the_pages_own_origin_may_call_the_routes`). Checked once
  by hand in headless Chromium against copies of the fixtures: no console
  error, no policy violation, and no request to anything but the service.
- **three.js** is vendored as published (0.185.1, MIT), its hashes pinned
  against the npm package (`test_the_vendored_three_js_is_the_published_release_unchanged`).
  It runs in the browser only; the service never runs it.
- **The condition.** A page is served by whatever holds the port, so a program
  that takes a stopped service's port could serve a page asking for the token
  (finding 15's case, for a person rather than a program), and the page cannot
  check the service as a client does. API 8.18 therefore says to use the viewer
  on a machine one person uses, with a token of its own.

## 2. The desktop app

`SolidSeasViewer.exe` is the viewer, and with the `[ai]` extra the modeling
assistant (`docs/ASSISTANT.md`): a Review mode that drafts code a person runs,
an Automatic mode that carries out a validated plan on one part, a chat server
for MCP clients (`--mcp`, `docs/MCP.md`) with the Gridfinity tools
(`docs/GRIDFINITY.md`), and the SOLIDWORKS bridge that all of them reach
SOLIDWORKS through. This section covers the AI connector, the script runner,
the bridge, what the app stores and the machine policy, as `docs/ROADMAP.md`
asks of Phase 5. Section 3 covers the extension packages and the OCCT helper.

### 2.1 Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 34 | Review mode runs whatever Python the person approves, with the person's rights, and no machine policy value turns it off. `SolidSeasViewer.exe --assistant-child` is that runner's child: it reads a script from standard input and runs it, so wherever the viewer is allowed to run, an allowlist (AppLocker, WDAC) that keeps Python itself off the PC does not keep Python code off it. The Job Object caps memory, processes and time; it is not a sandbox, as `docs/ASSISTANT.md` says. | Medium | Needs a decision: a `DisableScripts` policy value that the child checks before it compiles anything, and the window before it offers Run (follow-up). Until then, allow the viewer only where its users may run code of their own |
| 35 | `--set-policy` runs elevated from wherever SolidSeas is installed, and the installer's default is a per-user install (`PrivilegesRequired=lowest`) under the user's own profile, which any program that user runs can change. Code planted there runs as an administrator the next time one runs `--set-policy` from it, the bootloader, the Python runtime and `solidseas` itself all loading before any check could run. | Medium | Condition: run `--set-policy` only from an all-users install under `C:\Program Files`, or set the values with Group Policy, Intune or `reg.exe` (said now in `docs/ASSISTANT.md` and the user guide). The "Lock for all users" button, not built, must offer it only from such an install (follow-up) |
| 36 | The policy is SolidSeas' own code, so it binds an unchanged installation only: in a per-user install the enforcing code sits in a folder its user can change, and anyone may run a copy of their own. | Low | Accepted, with condition: install for all users, and use AppLocker or WDAC where only that copy may run. `docs/ASSISTANT.md`, "What the policy is not", says so |
| 37 | Under `LocalProviderOnly`, a host name in `AllowedProviderHosts` is trusted to whatever name resolution answers for it; only `localhost` is checked to resolve to loopback. A single-label name can be answered by any machine on the network segment (LLMNR, NetBIOS), and over `http://` nothing proves the server is the one meant, so the part summary and pictures go to whoever answers. | Low | Condition: list an IP address, or a full name served over HTTPS. Requiring HTTPS for a listed name under the policy is a follow-up for a decision |
| 38 | API keys are generic credentials of the user's account: any process running as the user can read them with `CredReadW`, and a key read stays in the app's memory as a Python string. | Low | Accepted: the same holds for any per-user secret; Credential Manager keeps them off disk files, out of roaming and out of other accounts |
| 39 | Token and cost budgets are the user's own settings (`AI.json`), not an administrator's control. | Low | Accepted: a spending limit an organisation needs belongs in the provider's own console |
| 40 | `--set-policy` wrote the removal of `AllowedProviderHosts`, which narrows the policy, with the removals that relax it, after any DWORD set to 0, so a write that stopped part way could relax a value before narrowing this one; and its `GetUserNameExW` call had no declared types. | - | Fixed during this review: what only adds a restriction (DWORDs set to 1, and that removal) is written first, and the call is declared. Verified: `test_removing_the_extra_hosts_counts_as_a_restriction_and_comes_first`, `test_restrictions_are_written_first_and_what_relaxes_one_last` |
| 41 | Three statements of `docs/ASSISTANT.md` and `setpolicy.py` did not match the code: that `main` calls `truststore.inject_into_ssl()` (nothing does; the connector builds its own context), that the policy is enforced in two chokepoints "and nowhere else" (the MCP server checks it too, before them), and that `--set-policy`'s exit code shows "either way" (the packaged executable has no console, a prompt does not wait for it, and after `\| more` the code a prompt shows is the pipe's). | - | Fixed during this review, in the documents. The exit code's behaviour is by inspection, not tried on Windows |
| 42 | The chat server passed the text of a file error to the chat: `show_part` for a part whose saved file was moved or locked, and any `OSError` from a tool, sent the file's full path, with the user's name in it, to the chat's model, where `docs/MCP.md` says no path goes. | Low | Fixed during this review: the chat is told the system's reason only. Verified: `test_a_picture_that_cannot_be_made_never_names_the_file`, `test_a_failed_file_call_is_said_to_the_chat_without_its_path` |
| 43 | A Gridfinity bin laid out by hand with a grid skipped the limit of 100 cells a bin may have, so a chat could have Tracefinity build a 25 x 25 bin of 625 cells. | Low | Fixed during this review. Verified: `test_a_layout_by_hand_that_does_not_fit_says_why_and_makes_nothing` |
| 44 | The Tracefinity tunnel found `ssh` with `shutil.which`, which on Windows looks in the current folder first, and fell back to the bare name, which `CreateProcess` also looks for there. The chat server's current folder is wherever the MCP client starts it, often a project folder, so an `ssh.bat` in a cloned project would have run on the first Gridfinity call once a tunnel is set up. | Low | Fixed during this review: Windows' own OpenSSH client first, else one on PATH that is not in the current folder, else a plain refusal. Verified: `test_ssh_is_never_one_in_the_current_folder` |
| 45 | The tunnel refused a server key it had not seen only through ssh's default, which a person's ssh config (`StrictHostKeyChecking accept-new` or `no`) changes. | Low | Fixed during this review: the tunnel passes `StrictHostKeyChecking=yes`. Verified: `test_a_tracefinity_on_a_server_is_reached_through_an_ssh_tunnel` |
| 46 | A bin's temporary file (`<name>.stl.part`) was opened for writing whether or not it existed, so a file or link already under that name was written through. | Low | Fixed during this review: the name counts as taken, and the file is created only new. Verified: `test_a_part_file_already_in_the_bins_folder_is_never_written_through` |
| 47 | The picture of a part (`show_part`, "Show the AI a picture of the part", the look after each step) is drawn by reading the part's saved file in the window's or the chat server's own process, with the library's default bounds, where section 1 reads every document in a worker. The chat can ask for it on any part open in SOLIDWORKS without the person confirming. | Low | Open: draw it in a worker with the viewer's limits (follow-up) |
| 48 | The run journal records neither the person's answer to the confirmation box nor the planning prompt, although `docs/ASSISTANT.md` says the journal keeps the prompt that was sent: after a run, whether a plan was confirmed or started by itself is not on record. | Low | Open: journal both, or correct the document (follow-up) |
| 49 | The script runner's child starts, then is put in its Job Object, rather than starting suspended as the bridge and the helpers do; and the memory cap is per process with no total for the job (up to 16 processes of 2 GB). The script is sent only after the child is in its job, so nothing approved runs outside it. | Low | Open: start it suspended and add a job memory total (follow-up) |
| 50 | The chat server's confirmation box guards against the chat's model, not against other programs of the same user: an MCP client that can run commands or drive the screen as the person (Claude Code with a shell, say) could press Yes. No policy value forces "Always confirm" for chats. | Low | Accepted, with condition: on a managed PC, use chat clients that cannot act on the desktop, or leave the chat server unconfigured |
| 51 | The tunnel's local end, 127.0.0.1 on the Tracefinity port, is shared by every account signed in to the PC, and the tunnel uses whatever already listens there. | Low | Accepted: use the tunnel on a PC one person uses at a time |
| 52 | A frozen one-file build looked for `SolidSeas.SwBridge.exe` in a `dist` folder two levels above its package, which for a one-file build is the user's temporary folder (`%TEMP%\dist`), where any program the user runs can put one. | Low | Fixed during this review: only a source checkout looks in `dist`. Verified: `test_a_frozen_build_never_looks_for_the_bridge_in_a_dist_folder` |
| 53 | `SOLIDSEAS_SWBRIDGE`, meant for a developer's build of the bridge, was honoured before the machine policy, so under `DisableExtensions`, or an `AllowedExtensions` without the CAD Bridge, any program it named still ran as the bridge. | Low | Fixed during this review: the policy comes first. Verified: `test_the_solidworks_bridge_comes_from_the_bridge_s_package_while_it_is_on` |
| 54 | The CAD Bridge package's program was run without checking its files against the hashes the package was added with, which every other helper's files are checked against before each start (`docs/EXTENSIONS.md` section 6). | Low | Fixed during this review. Verified: `test_the_solidworks_bridge_comes_from_the_bridge_s_package_while_it_is_on` |
| 55 | Neither the bridge nor the viewer is code signed, and nothing checks the bridge program beyond the protocol number in its ready line. AppLocker or WDAC can allow them by path or hash only, and every update needs allowing again. | Medium | Needs a decision: code signing with the signed installer (bead SolidSeas-fg2); until then, allow by hash or by an administrator-only path |
| 56 | The bridge's named objects (`Local\SolidSeas-SwBridge-SolidWorks`, `Local\SolidSeas-Batch-<pid>`, `Local\SolidSeas-Live-<pid>`) have default security, so any process in the person's session can take one first: batch conversion then says another bridge is running, or a session looks held by a writer or hidden from the picker. Nothing can make the bridge attach to the wrong process. | Low | Accepted: a denial of service within the person's own session only |
| 57 | Ending the batch bridge's Job Object also ends the `swCefSubProc` helpers of SolidSeas' own SOLIDWORKS, which share a cache in the temporary folder with the person's SOLIDWORKS; what an unclean end does to that cache is not measured. | Low | Open: measure on the PC (bead SolidSeas-d30). An availability question, not a disclosure |
| 58 | Two protections of batch conversion have not run against a real SOLIDWORKS: the bridge's refusal to end its SOLIDWORKS while it shows a document SolidSeas did not open (its C# change was not built when it landed), and the put-back of the registry values SolidSeas' SOLIDWORKS changed. Both are tested with stand-ins only. The put-back also stops watching for another SOLIDWORKS just before it reads and writes back, so one started in that moment could have a value it just wrote put back. | Low | Open: build the bridge and run both on the PC before batch conversion is used where a person works in SOLIDWORKS |

The bead behind findings 56 and 57 (SolidSeas-d30) also noted that Python put
the bridge in its Job Object only after starting it. That is no longer so: the
helper runner starts the bridge suspended, puts it in its job, checks that it
is there and only then lets it run (`test_a_bridge_starts_suspended_and_runs_once_it_is_in_its_job`,
`test_a_bridge_left_outside_its_job_is_ended_at_once`, Windows).

### 2.2 What runs

| Process | Started by | What it is | Bounds |
|---|---|---|---|
| `SolidSeasViewer.exe` | the person | the viewer, the assistant window, or the chat server (`--mcp`, over standard input and output) | the person's rights |
| The script child (`--assistant-child`) | the assistant window, when the person presses Run | the same executable running one approved script | a Job Object with kill-on-close: 16 processes, 2 GB each by default, 300 s, Stop ends it at once; elsewhere than Windows, its own session, `RLIMIT_AS` and a death signal |
| `SolidSeas.SwBridge.exe` | the window, the chat server, or `python -m solidseas.swapi` | a C# program that speaks to SOLIDWORKS through COM, one JSON line a request over pipes | started suspended in a Job Object with kill-on-close; a deadline per request |
| `SLDWORKS.exe`, SolidSeas' own | the bridge, for batch conversion from the command line only | SOLIDWORKS, with no arguments | started suspended in the bridge's own Job Object with kill-on-close |
| `ssh` | the chat server, for a Tracefinity on another machine | the system's OpenSSH client with one local forward | a Job Object with kill-on-close; `BatchMode`, `StrictHostKeyChecking=yes` |
| Helpers of extensions (OCCT, video, SolidCraft) | the app, while the extension is on | section 3 | section 3 |
| Explorer, the mail program, a file's own program | the viewer, on the person's command | Windows' handlers for "Show in folder", mail and Open | from an argument list, never a shell |

The desktop app never starts batch conversion or SolidSeas' own SOLIDWORKS:
those are reached from the command line only. The window and the chat server
use the bridge's session list and its live operations on a SOLIDWORKS the
person already runs, attaching only to a process named `SLDWORKS.exe` in the
same Windows session through its own running-object entry, and never from a
bridge that is not elevated to a SOLIDWORKS that is.

### 2.3 Network surface

The complete set of outbound connections the desktop app makes itself:

| Connection | When | Evidence |
|---|---|---|
| HTTPS to `api.anthropic.com`, `api.openai.com` or `generativelanguage.googleapis.com` | a request to a configured cloud provider; the addresses are constants of the providers, never settings | Verified: `test_providers_are_constructed_only_in_the_factory` (only the factory builds a provider, and it passes an address to Ollama alone), `test_base_urls_are_checked` |
| HTTP or HTTPS to the Ollama address in the AI settings (`http://127.0.0.1:11434` until changed) | a request to Ollama | Verified: `test_local_only_allows_loopback_and_listed_hosts_only`, `test_localhost_is_pinned_to_a_loopback_address`, `test_a_pinned_client_connects_to_the_address_it_resolved` |
| An HTTP proxy, by CONNECT, for cloud providers only | when the environment or the static WinINET setting names one | Verified: `test_proxies_come_from_the_setting_and_loopback_never_uses_one` |
| HTTP to Tracefinity on 127.0.0.1 | a Gridfinity tool call; any other host is refused when the client is made, and `localhost` is checked to resolve to loopback on every call | Verified: `test_tracefinity_is_reached_on_this_pc_only`, `test_ids_are_checked_before_they_become_part_of_a_path` |

Nothing else: no update or licence check, no telemetry, no crash reporting,
and nothing listens. The chat server speaks over standard input and output
only, and the script child and the bridge over pipes.

| Claim | Evidence |
|---|---|
| A provider call never follows a redirect, so a key never goes where a reply points | Verified: `test_a_redirect_is_never_followed` |
| TLS is the operating system's trust store (`truststore`) or the standard library's default, TLS 1.2 at least, and nothing turns certificate checks off | Verified: `test_tls_comes_from_truststore_when_it_is_installed`, `test_tls_falls_back_to_the_standard_library`, and the search in 2.8 for `CERT_NONE` and the like finds nothing |
| A key travels in a request header only, never in a URL or a body, and no key, nor a provider's answer to a 401 or 403, reaches a message or the log | Verified: `test_plan_steps_sends_the_shared_prompt_and_reads_the_reply`, `test_a_401_with_a_known_key_shows_the_key_nowhere`, `test_401_and_403_stop_at_once`, `test_a_key_the_200_character_cut_splits_is_still_hidden`, `test_provider_text_quoted_in_an_error_is_scrubbed` |
| A reply is bounded in size, time and parsing cost | Verified: `test_a_reply_larger_than_the_cap_is_refused`, `test_a_trickling_reply_cannot_hold_the_call_open`, `test_a_server_that_never_answers_times_out`, `test_a_hostile_reply_is_read_in_linear_time` |
| No test reaches a network | Verified: the suite's autouse `no_network` fixture fails any connection or name lookup to a host other than loopback (`tests/conftest.py`) |
| The bridge and its Python client open no socket | By inspection, and the search in 2.8 finds no network code in the bridge |

What will show up anyway, and is not SolidSeas' own connection:

- **ssh.** With a Tracefinity on another machine, `ssh` connects to the server
  the person set up, opens a listener on 127.0.0.1 at the Tracefinity port,
  and forwards it to the same port on the server's loopback only. The setup
  script limits the key on the server to that one forward.
- **File shares.** Opening a file on a share makes Windows connect to that
  server, as the person. The viewer's own lookups of a file a document names
  never go to a UNC path or a mapped network drive (section 3.6).
- **SOLIDWORKS itself**, which the bridge drives, may reach a licence server or
  its activation service, the files an assembly names on shares, and web
  content in its own embedded browser, as its installation is set up.
- **Windows** opens the releases page (Extensions, "Get extensions") in the
  person's browser, and a mail program sends what the person sends.

### 2.4 Code execution surface

**Review mode.** The model's draft goes into the console editor and nothing
runs until the person presses Run; the editor is read-only while a script
runs, and what runs is the text the person saw. The script runs in the child
process of 2.2 as ordinary Python with the person's rights. It reaches
SOLIDWORKS only through the app: each request must be one of the read-only
queries or an operation of the closed vocabulary, checked again against the
part's snapshot, at most 10,000 calls a script, after the one-writer lock is
taken and a safety copy of the part is saved. Verified (tests/test_assistant_review.py):
`test_a_draft_appears_in_the_console_and_nothing_runs_until_run`,
`test_a_script_runs_in_a_child_process_and_reaches_solidworks_only_through_the_app`,
`test_what_a_script_prints_is_data_never_a_protocol_line`,
`test_a_script_over_its_memory_cap_is_stopped_by_the_cap`,
`test_a_script_over_its_time_is_ended_and_the_next_runs`,
`test_stop_ends_a_script_at_once`,
`test_the_child_ignores_the_environments_python_settings`,
`test_one_writer_holds_the_session_while_a_script_runs_and_gives_it_back`.
The process limit of 16 and the end of a script's own children on Stop are by
inspection.

**Automatic mode** never runs free code. A plan is JSON in the closed
vocabulary, checked by one parser against the part's snapshot (an unknown
operation, a number that is not finite, a protected property or another
vocabulary refuses the whole plan), and `start_run` is its only entry, which
reads the policy, takes the writer lock and saves checkpoint 0 before step 1.
Verified: `test_start_run_is_the_only_entry_to_automatic_mode`,
`test_an_unknown_operation_refuses_the_plan`, `test_non_finite_values_refuse_the_plan`,
`test_protected_properties_are_never_written`, `test_a_plan_for_another_vocabulary_is_refused`,
`test_start_run_honours_each_result`.

**The chat server.** A chat lists sessions, reads summaries, gets pictures,
runs plans as Automatic runs, keeps or reverts its own runs, and uses the
Gridfinity tools. It cannot run code (the runner is built by the window
alone), name a file path (documents are ids the server makes; a photo is a
bare name of a plain file in the photos folder; a bin's name keeps only
letters, digits and a few marks), or choose a folder, an ssh server or an
address. A plan that sets a dimension, suppresses or unsuppresses a feature,
or writes a property waits for the person's Yes in a box of SolidSeas' own,
No by default, and every plan does when "Always confirm" is on; finding 50 says
what that box does not guard against. Every number of the hand placement
tools is checked in code, whatever the schema says (finite, within its range,
on every tool or none). Verified (tests/test_assistant_mcp.py and
tests/test_gridfinity.py): `test_a_plan_that_overwrites_waits_for_the_person_on_this_pc`,
`test_a_plan_cancelled_while_the_person_is_asked_never_starts`,
`test_a_plan_for_a_part_changed_since_it_was_read_is_refused`,
`test_the_policy_is_read_at_every_call`, `test_file_names_from_the_chat_stay_names`,
`test_a_photo_is_named_by_a_plain_file_in_the_folder`,
`test_a_bin_is_laid_out_made_and_saved_without_writing_over_a_file`,
`test_a_layout_by_hand_that_does_not_fit_says_why_and_makes_nothing`,
`test_tools_placed_by_hand_from_the_chat_go_where_it_says`.

**The bridge** runs only its named operations, never code: no macro, no
compiler, no process start but SOLIDWORKS for batch conversion, and no
assembly loaded but the SOLIDWORKS interop assemblies from the installation's
`api\redist` folder. Requests are refused past 1 MiB, with an unknown field,
operation or argument, or with a path that is not an absolute path on a drive
(a network path only where batch conversion was given one). Source documents
are opened read-only, always. SOLIDWORKS writes a native part in three places
only, each a copy to a new file: the safety copy of a live part, in the run's
own folder; a batch check's copy; and the test session's. Exports never write
over an existing file or over a file open in SOLIDWORKS, and live mode never
saves, closes or ends the person's work. Its window watch only hides the
journal-file message box of its own SOLIDWORKS. Verified by reading the C#
source in `tests/test_swapi.py` (`test_bridge_offers_only_its_named_operations`,
`test_bridge_never_saves_a_document_or_changes_an_option`,
`test_save_copy_writes_export_formats_only_and_never_over_an_open_file`,
`test_live_mode_never_ends_closes_or_saves_the_persons_work`,
`test_the_window_watch_hides_only_the_journal_box_of_its_own_solidworks`), and
on Windows with the bridge built (`test_real_bridge_takes_only_paths_on_a_drive`,
`test_a_request_longer_than_the_bridge_reads_is_never_sent`). No argument from
a model or a chat names a file, a program or a document: documents are the
bridge's own keys for what the attached session has open, and a plan's values
are numbers and the bridge's own references.

**`--set-policy`** is dispatched before anything imports Qt, opens a document
or reads a settings file, and runs no other process; section 2.7.

**Native calls** are `ctypes` calls with declared types: `advapi32`'s
`CredReadW`, `CredWriteW`, `CredDeleteW` and `CredFree`; `shell32`'s
`IsUserAnAdmin` and `secur32`'s `GetUserNameExW` for `--set-policy`;
`kernel32` for Job Objects and the writer mutex; `user32`'s `MessageBoxW` for
the chat's confirmation box; and on Linux `prctl` in libc. No `pickle`,
`marshal` or `eval` anywhere in the app, and one `exec`, the script child's.

### 2.5 Untrusted input

- **Model replies** are read by one parser in time linear in their length, at
  most 400,000 characters, refusing numbers that are not finite; validated
  against a schema and allowlists; never allowed to choose a file path, URL or
  document; and shown as plain text only (`test_model_text_is_shown_as_plain_text_everywhere`).
- **What leaves the machine** is built in one place, `build_model_summary`,
  field by field, with names replaced by handles unless the person ticks
  "Send my feature and property names" for the run, and never paths, property
  values, author fields, stored previews or annotation text
  (`docs/ASSISTANT.md`, "What leaves the machine"; `tests/test_ai_context.py`).
- **The chat** is untrusted as a model reply is (2.4), and what a chat is told
  never holds a path on the PC (finding 42).
- **Part files** are read for the picture of a part in the app's own process
  (finding 47); every other read follows the viewer's rules.

### 2.6 What it stores

| What | Where | Contents | Protection and how long |
|---|---|---|---|
| Run folders | `%LOCALAPPDATA%\SolidSeas\runs\<run id>\` (the id SolidSeas makes) | `checkpoint-<id>.sldprt`, a full copy of the person's part; the copy after each step when the look after each step is on; `journal.jsonl`, with the part's path and title, its state before and after each step (feature and dimension names, custom and configuration property values, material, equations), the plan and each look's prompt; `run.lock` | The profile's access list; `run.lock` created exclusively without following a link. Until Keep or Revert, then 7 days; the clean-up skips links, junctions and anything not a plain file (`test_a_link_in_the_runs_folder_is_never_followed`, `test_a_junction_in_the_runs_folder_is_never_followed`). Never sent to a model, never named to a chat |
| The bridge's markers | `%LOCALAPPDATA%\SolidSeas\live-undo-<pid>.txt`, `live-lock-<pid>.txt` | A document key and an undo name | Created new, removed after use |
| SOLIDWORKS options held during a run | `%LOCALAPPDATA%\SolidSeas\sw-options.json` | The option values changed | Until restored |
| Usage | `%LOCALAPPDATA%\SolidSeas\usage.json`, with `usage.json.lock` | Monthly counts per provider and the holds of calls in flight, no prompt text | The profile's access list; written to a temporary file and replaced, under a cross-process lock (`test_two_processes_recording_at_once_lose_no_increment`). The last 24 months |
| AI settings | `%APPDATA%\SolidSeas\AI.json` (roams) | Provider, model, Ollama address, budgets, prices and limits, never a key | Written through a temporary file and a rename, never through a link (`test_save_never_writes_through_a_link`) |
| Extension settings | `%APPDATA%\SolidSeas\Extensions.json` | Which extensions are on; Gridfinity's folders, ssh server, the path of the ssh key (never the key) and Tracefinity's address | Until changed |
| API keys | Windows Credential Manager, `SolidSeas/<provider>` | The key | The user's credential store, local to the PC (`CRED_PERSIST_LOCAL_MACHINE`), shown nowhere (`test_the_key_field_never_shows_a_stored_key`); finding 38 |
| Gridfinity bins | the bins folder, `Documents\Gridfinity bins` unless set | The STL, 3MF and zip files made | Never written over (finding 46); kept until the person deletes them |
| Tracefinity's library | `%LOCALAPPDATA%\SolidSeas\tracefinity\storage`, or the server's | Each photo traced, and the tools and bins made | Tracefinity's own; SolidSeas never clears it |
| Machine policy | `HKLM\SOFTWARE\Policies\SolidSeas`, 64-bit view | The six values, `SetBy` and `SetAt` | Read only, except through `--set-policy` (2.7) |
| SOLIDWORKS' own settings | `HKCU\Software\SolidWorks\SOLIDWORKS <year>\User Interface` and `General\Last Splash Id` | Values SolidSeas' own SOLIDWORKS changed, put back | Batch conversion from the command line only, and only when no other SOLIDWORKS ran meanwhile and the value is still what that instance left (finding 58); never any other key (`WinRegistry` refuses it) |
| Batch outputs | the folder the person names, with `report.tsv` | Exported files, whose STEP and Parasolid headers carry the Windows user name and a machine id SOLIDWORKS writes | Never over an existing file, never into a folder holding a source document |

Nothing is written to the registry but the two rows above. No credentials are
requested, used or stored besides the providers' API keys, and the ssh key
the Tracefinity setup script makes in the person's `.ssh` folder, which
SolidSeas passes to ssh by its path and never reads.

### 2.7 The machine policy

The policy is read in `solidseas/policy.py`, fail-closed, as
`docs/ASSISTANT.md`, "Machine policy", describes: a missing key is no policy,
any other error turns every restriction on, a value of the wrong type or out
of range turns its restriction on, and the registry is read again before every
run and model call. Verified (tests/test_ai_policy.py):
`test_a_key_that_access_is_denied_to_turns_every_restriction_on`,
`test_any_other_error_opening_the_key_turns_every_restriction_on`,
`test_a_wrong_type_or_out_of_range_value_turns_that_restriction_on`,
`test_a_reader_that_raises_means_every_restriction_is_on`,
`test_the_reader_never_checks_existence_first`,
`test_the_real_reader_opens_the_64_bit_view_and_treats_a_missing_key_as_no_policy`,
`test_a_policy_pushed_while_the_app_runs_applies_to_the_next_call`. Neither
the reader nor the writer checks the key's own access list: they rely on
Windows', under which only administrators and SYSTEM change
`HKLM\SOFTWARE\Policies`.

It is enforced in the provider factory and in `start_run`, and every provider
checks `LocalProviderOnly` itself, from its own kind and address, before each
call and health check, so one built some other way still fails closed
(`test_a_provider_built_outside_the_factory_still_obeys_the_policy`,
`test_an_ollama_built_outside_the_factory_checks_its_own_address`,
`test_the_guard_runs_before_every_call_and_health_check`). `DisableImages` is
applied on the one call path every provider takes
(`test_an_administrator_can_forbid_pictures`). The chat server checks it too,
before either chokepoint: under `LocalProviderOnly` every tool refuses, and
under `DisableAutomaticMode` `run_plan` does. Two searches show the
chokepoints, and `tests/test_ai_factory.py` repeats both on every test run
(the first through Python's syntax tree, so an alias or a call through a table
is caught too):

```text
git grep -nE "(Anthropic|OpenAI|Gemini|Ollama|Noop)Provider\b|(CLOUD|LOCAL)_PROVIDERS|(\.|import )providers\b" -- src ":!src/solidseas/ai/providers" ":!src/solidseas/ai/factory.py"
git grep -nE "\bstart_run\(" -- src
```

Expected: the first looks everywhere but the providers' own package and
`src/solidseas/ai/factory.py`, which builds them (the cloud providers through
its `CLOUD_PROVIDERS` table), and finds only the package notes in
`src/solidseas/ai/__init__.py` and `src/solidseas/ai/fake.py` importing the
shared base class `ChatProvider` for the test stand-in, and a docstring in
`src/solidseas_app/assistant/aisettings.py` that names `NoopProvider`, so
nothing else names a provider class or table or imports the package. The
second finds the
definition in `src/solidseas_app/assistant/automatic.py` and its two callers,
the window (`window.py`) and the chat server (`mcp_server.py`).

The app reads the policy key and never writes it, except through
`SolidSeasViewer.exe --set-policy` (`src/solidseas_app/setpolicy.py`), which an
administrator runs elevated as a step of its own (finding 35 says from where).
It refuses unless `IsUserAnAdmin` says the process is elevated, checks every
argument before anything is written, writes what only adds a restriction
first, records `SetBy` and `SetAt`, and reads the policy back with the reader
itself. `--remove-all` deletes the key and every value in it. Verified
(tests/test_set_policy.py): `test_only_a_process_windows_calls_elevated_writes`,
`test_an_elevation_check_that_fails_counts_as_no`, `test_a_usage_error_writes_nothing_and_asks_nothing`,
`test_restrictions_are_written_first_and_what_relaxes_one_last`,
`test_a_write_that_stops_part_way_says_what_was_written_and_how_the_policy_reads`,
`test_a_value_that_does_not_read_back_as_written_is_a_failure`,
`test_the_real_writer_changes_the_key_the_reader_reads_in_the_same_view`. The
registry writes are in two files, and `tests/test_set_policy.py` repeats this
search on every test run through Python's syntax tree
(`test_the_policy_key_is_written_only_by_set_policy`):

```text
git grep -nE "\b(CreateKey|CreateKeyEx|DeleteKey|DeleteKeyEx|DeleteValue|SetValue|SetValueEx|SaveKey|LoadKey|RegCreateKeyExW|RegSetValueExW|RegSetKeyValueW|RegDeleteKeyExW|RegDeleteValueW|RegDeleteTreeW)\b" -- src
```

Expected: two files. `src/solidseas_app/setpolicy.py`, whose `WindowsPolicyKey`
opens the key in the same 64-bit view the reader uses, and
`src/solidseas/swapi/hkcu.py`, which writes nothing but SOLIDWORKS' own settings
under `HKEY_CURRENT_USER\Software\SolidWorks` (its `WinRegistry` refuses any other
key) after a batch conversion, never the policy key.

What the policy is not, as `docs/ASSISTANT.md` says: it removes SolidSeas' own
ability to send model data off the PC and to run Automatic mode; it is not a
sandbox (finding 34), it binds an unchanged installation only (finding 36), and
anyone who can edit the key can undo it. Where a hard guarantee is needed, pair
`LocalProviderOnly` with an outbound firewall rule for the executable.

### 2.8 Repeating the checks

From a checkout, with the development dependencies and the `[ai]` extra
installed:

```text
python -m pytest -q tests/test_ai_http.py tests/test_ai_providers.py tests/test_ai_factory.py tests/test_ai_policy.py tests/test_ai_credentials.py tests/test_ai_usage.py tests/test_ai_context.py tests/test_ai_prompts.py tests/test_ai_automatic.py tests/test_set_policy.py tests/test_assistant_review.py tests/test_assistant_mcp.py tests/test_assistant_automatic.py tests/test_gridfinity.py tests/test_swapi.py tests/test_swapi_hkcu.py tests/test_extensions.py
```

Expected: every test passes; on Linux the Windows-only tests skip (Job
Objects, Credential Manager, the registry, the built bridge), and the tests
that start SolidSeas' own SOLIDWORKS skip unless `SOLIDSEAS_SWAPI_SOLIDWORKS=1`.

```text
git grep -nE "^\s*(import|from) (socket|ssl|http\.client|urllib\.request)\b" -- src
```

Expected: `src/solidseas/ai/http.py` (the connector's client, which
Tracefinity's client reuses), `src/solidseas/serve/server.py` (section 1), and
`src/solidseas_app/gridfinity/tunnel.py`, whose `socket` only checks whether
something listens on 127.0.0.1.

```text
git grep -nE "check_hostname|CERT_NONE|_create_unverified_context|verify_mode" -- src
```

Expected: nothing.

```text
git grep -nE "subprocess\.(Popen|run)\(" -- src
```

Expected: `src/solidseas/helpers.py` (the bridge and the extension helpers),
`src/solidseas/swapi/build.py` (the C# compiler, a developer's command),
`src/solidseas_app/assistant/runner.py` (the script child),
`src/solidseas_app/extensions/video_helper.py` (two, section 3),
`src/solidseas_app/gridfinity/tunnel.py` (ssh), and in
`src/solidseas_app/viewer/` `mail.py`, `opening.py` and `printing.py`
(Explorer, a file's own program, SolidCraft). Every one passes an argument
list, never a shell.

```text
git grep -nE "(^|[^.A-Za-z_])(exec|eval|compile)\(" -- "src/solidseas_app/*.py"
```

Expected: `src/solidseas_app/assistant/child.py`, the script child's `compile`
and `exec`, and a dialog's own `exec` method in
`src/solidseas_app/viewer/drawingsettings.py`.

```text
git grep -nE "CreateProcess\(|Process\.Start|ShellExecute|RunMacro\(|cmd\.exe|System\.Net|WebClient|HttpWebRequest|Socket|NamedPipe" -- "src/solidseas/swapi/SwBridge/*.cs"
git grep -nE "SaveAs3\(|\.Save3\(|\.Save2\(|\.Save\(" -- "src/solidseas/swapi/SwBridge/*.cs"
```

Expected: the first finds the declaration and the one call of `CreateProcess`
in `Native.cs` and its caller in `Operations.cs`, which starts SOLIDWORKS for
batch conversion, and nothing of the network; the second finds the three
copies of 2.4 (`Live.cs`, `NativeCheck.cs`) and the export in `Operations.cs`.

On Windows, while the assistant window or the chat server runs:

```powershell
Get-CimInstance Win32_Process -Filter "Name='SolidSeasViewer.exe' OR Name='SolidSeas.SwBridge.exe' OR Name='ssh.exe'" |
  Select-Object ProcessId, ParentProcessId, CommandLine
Get-NetTCPConnection -OwningProcess <pid>   # for each
Get-NetUDPEndpoint -OwningProcess <pid>
```

Expected: no `Listen` for any SolidSeas process; connections only to the
provider in use (or its proxy) while a request is in flight; with a tunnel,
`ssh.exe` listening on 127.0.0.1 at the Tracefinity port and connected to the
server; no UDP endpoint.

### 2.9 Recommendation

Suitable for a managed Windows PC, with these conditions:

1. Install for all users, under `C:\Program Files` (findings 35 and 36, and
   finding 4 of section 1), and set the machine policy by Group Policy, Intune
   or `reg.exe`, or with `--set-policy` run from that installation only.
2. Decide on code signing (finding 55); until then, allow the viewer and the
   bridge in AppLocker or WDAC by hash or by an administrator-only path.
3. Decide whether its users may run code of their own (finding 34): the viewer
   runs approved Python, and no policy value turns Review mode off yet.
4. Where part data must not leave the PC, set `LocalProviderOnly`, list any
   Ollama server by IP address or by a full name served over HTTPS (finding
   37), and add an outbound firewall rule for the executable. Set
   `DisableAutomaticMode` and `DisableImages` where those are not wanted.
5. Configure the chat server only for chat clients that cannot act on the
   desktop as the person (finding 50), and the Tracefinity tunnel only on a PC
   one person uses at a time (finding 51).
6. Before batch conversion is used on a PC where a person works in
   SOLIDWORKS, run the bridge's refusal and the registry put-back on that PC
   (finding 58).

## 3. The OCCT backend, extension packages and lookups outside the folder

Open CASCADE (OCCT) reads IGES and BREP files, converts between STEP, IGES and
BREP (File > Convert, `solidseas convert`) and cross-checks a written STEP
file (`export --check`), as tier 1 of `docs/OCCT.md`. In the evaluation it
crashed on 1 in 7 damaged STEP files and 1 in 3 damaged IGES files, so it runs
only out of process, in a helper, never in SolidSeas' own processes. It comes
as an extension package (`docs/EXTENSIONS.md`), as do the CAD Bridge (section
2), video export and SolidCraft.

### 3.1 Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 59 | The copy of a file the helper reads (`%TEMP%\solidseas-occt-*\in\model.*`) is removed after the request, but not when the process that made it is killed first: a REST worker at its deadline (10 to 60 s, against OCCT's measured 75 s for a large file), a crashed export process, a cancelled Convert. Nothing sweeps them, so copies of documents under a root collect in the account's temporary folder, and `docs/API.md` 8.13's "removed after the file" is then untrue. | Low | Open: sweep old staging folders when the backend first starts in a process (follow-up). Until then, condition 7 of 1.8 |
| 60 | While the helper may start, a REST pool's process limit is set for the whole pool and allows any program, so a parser bug that ran code in one worker (finding 5) could start other programs, up to the number of workers, which `test_a_worker_cannot_start_another_process` shows impossible otherwise. They stay inside the pool's Job Object (memory cap, kill-on-close). | Low | Open: a nested Job Object per worker that allows its helper alone (follow-up). Off unless `--formats` names `iges` or `occt_brep` or `all` and the backend is available |
| 61 | A package's files are checked before each start against the hashes of the manifest in its own folder, and the core's list of accepted packages only when the package is added. Whoever can write that folder, `%LOCALAPPDATA%\SolidSeas\extensions\<id>\`, which is any program the account runs, can replace a helper and its manifest together. A REST service run as a person's account would then start a program from that person's profile. | Low | Open: record each package's manifest hash in the accepted list, and check the installed manifest against it before each start (follow-up). Condition 7 of 1.8 |
| 62 | `SOLIDSEAS_OCCT_HELPER_PYTHON`, a source checkout's way to name the Python that runs the helper, was honoured before the machine policy, so under `DisableExtensions`, or an `AllowedExtensions` without OCCT, the program it named still ran, in the command line and in the service. | Low | Fixed during this review: the policy comes first. Verified: `test_the_machine_policy_holds_for_a_checkouts_helper` |
| 63 | Add from file unpacked a package for an extension the machine policy leaves off (it could not run while the policy held), where the packages that come with the viewer are refused in that case. | Low | Fixed during this review: it is refused with "Set by your administrator" and not unpacked. Verified: `test_a_package_an_administrator_left_off_is_never_unpacked` |
| 64 | A helper started from the packaged viewer inherits its environment and DLL search order, the viewer's own unpacked folder included, where the other programs the viewer starts have both cleaned. | Low | Open: check on Windows with the first OCCT build, and clean them as for the other programs (follow-up) |
| 65 | Add from file checks the zip and then opens it again by its path to unpack it, so a program of the same user could swap it in between. | Low | Open: check and unpack one private copy (follow-up). Only the same account can do it, and that account can already change the installed package (finding 61) |
| 66 | No damaged IGES or BREP file has been through the service with the real helper: that a crash or a hang costs one answer is shown with a stand-in helper and by inspection, and whether the IGES reader follows external references (entity type 416) is not tested. | Low | Open: run the damaged files of the evaluation through `serve --formats iges` (follow-up) |
| 67 | The drawing editor's lookup of a drawing's model by its stored path refused UNC paths and mapped drives but went through a link or junction on the way, so a crafted drawing on a local volume holding a folder link to a share made Windows connect to that share as the person. The viewer's own lookups stopped at such a link already (commit 18488c5). | Low | Fixed during this review: each folder on the stored path is looked at before the next, and a link stops the lookup. Verified: `test_a_stored_path_through_a_link_is_not_followed` |

### 3.2 The helper

- **How it starts.** Through the helper runner (`solidseas/helpers.py`):
  `subprocess.Popen` from an argument list, never a shell; on Windows started
  suspended, put in a Job Object of its own with kill-on-close, a memory cap
  and no error box, checked to be in it, and only then let run. From a package
  the program is `solidseas-occt.exe`, after `start_helper` checked that the
  extension is on, the policy allows it and every file still has its SHA-256;
  from a checkout, the Python `SOLIDSEAS_OCCT_HELPER_PYTHON` names runs the
  checkout's helper module with `-I`. Memory 3072 MiB, a request at most 300 s
  (checkout) or the manifest's `seconds`.
- **Inside it.** It turns off Windows' error boxes and, elsewhere, core dumps,
  caps its own memory at no more than the limit it inherited, and ends with its
  parent. Its standard output is the null device before OCP loads, so nothing
  Open CASCADE prints can be taken for an answer. It imports the standard
  library and OCP only, and nothing in SolidSeas imports it; it is left out of
  the viewer's build. Verified: `test_the_helper_imports_the_standard_library_and_ocp_only_and_nothing_imports_it`.
- **The conversation** is JSON lines over pipes, never pickle: four requests
  (`convert`, `check`, `version`, `shutdown`), a request line at most 4 MiB, a
  reply at most 64 MiB. A path on a share, a link, a format outside its tables
  or a name that is not plain ASCII is refused. Of a reply, the core keeps typed
  numbers and short printable strings only, and a message is fixed text or an
  exception's class name. Verified: `test_the_helper_s_conversation_holds_without_open_cascade`,
  `test_the_core_takes_only_what_the_helper_was_told_to_write`.
- **What it reads and writes.** Never the document itself: the bytes SolidSeas
  already read under its own rules go to a new folder from `tempfile.mkdtemp`
  under a fixed name (`model.igs`, `model.brep`, `model.step`), created only
  new, so no link in the source is followed and no name from a file reaches
  the disk. The result is read only from the one file the helper was told to
  write, after a link check, at most 1 GiB. The folder is removed afterwards
  (finding 59 says when not). Verified: `test_an_iges_file_reads_through_the_backend_as_a_step_model`,
  `test_a_file_that_takes_too_long_ends_the_helper`.
- **Network.** None: the helper opens no socket, and Open CASCADE's basic
  readers are used, not the XCAF ones. By inspection.

### 3.3 What it adds to the REST service

The service's workers may start the helper only when `--formats` names
`iges` or `occt_brep`, or `all`, and the backend is available when the service
starts; a pip installation accepts no package of its own, so that means a
checkout's `SOLIDSEAS_OCCT_HELPER_PYTHON` or a package the service's account
added in the viewer. Then each worker may start one helper, which runs in a
Job Object nested in the pool's, so the pool's 2 GiB cap per process holds for
it, and it ends when its worker is killed at a deadline or the pool closes
(by inspection; finding 60 says what the pool's process limit allows).
Verified: `test_only_pools_that_read_iges_or_brep_let_their_workers_start_the_helper`,
`test_the_rest_service_s_workers_start_the_helper_only_for_iges_and_brep`, and
with Open CASCADE installed `test_the_rest_service_reads_iges_geometry_through_the_helper_program`.
Up to four workers and four helpers, each held to 2 GiB, can then be running.
Section 1.2, 1.4, 1.5, 1.6 and 1.8 say this where it applies.

### 3.4 File > Convert and `export --check`

File > Convert runs in the viewer's export process, a worker in a Job Object
with kill-on-close and a memory cap, which starts the helper. The file is
written beside the chosen one as a hidden `.part` file and renamed into place;
the target must be outside the opened folder and the document's own folder.
Verified (tests/test_viewer_convert.py): `test_convert_runs_in_the_export_process_and_writes_the_chosen_file`,
`test_convert_refusals_write_nothing`. `export --check` starts the helper from
the command line's process to read back the STEP file it wrote, and writes
nothing. The drawing cross-check against Open CASCADE (commit 516698f) is a
test of the suite only, in no shipped code.

### 3.5 Extension packages

- **What is accepted.** A package is accepted only when its zip's SHA-256 is in
  the list the release build writes into the core (`accepted.json`); a source
  checkout or a pip installation accepts none. Its manifest must name
  SolidSeas as publisher and match the core's own idea of that extension, list
  exactly the zip's files, and give each one's SHA-256. Verified (tests/test_extensions.py):
  `test_a_package_from_another_release_or_changed_is_refused`,
  `test_a_source_checkout_accepts_no_package`.
- **Unpacking.** Entry names are plain (letters, digits and a few marks; no
  `..`, drive, absolute path, device name, trailing dot or space, or two names
  that differ only in case), no link, each at most 1 GiB at a ratio of at most
  200 and the package at most 2 GiB and 20,000 entries; files are created only
  new in a temporary folder renamed into place under
  `%LOCALAPPDATA%\SolidSeas\extensions\<id>\`. Verified:
  `test_a_package_whose_entries_leave_its_folder_or_differ_is_refused`,
  `test_a_link_a_bomb_a_wrong_file_or_a_manifest_that_differs_is_refused`,
  `test_the_package_folder_is_never_a_link_followed`.
- **Running.** No package's code is imported into SolidSeas' own processes. A
  helper starts only while its extension is on and allowed, and only after its
  files are checked again (`test_a_packaged_extension_s_helper_runs_only_while_on_and_unchanged`,
  `test_the_extension_s_package_and_switch_decide`); the CAD Bridge's program
  now is too (finding 54). `DisableExtensions` and `AllowedExtensions` are read
  at every check, and hold for Add from file (finding 63), for the packages
  beside the viewer, and for the variables a developer sets (findings 53, 62).
- **Not reviewed here.** The video helper (ffmpeg, from an argument list, on
  frames SolidSeas rendered; `SOLIDSEAS_FFMPEG` names another ffmpeg) and
  SolidCraft (its MCP tools in the chat server, and Open in SolidCraft, which
  starts SolidCraft's program on a STEP copy outside any Job Object, so it
  outlives the viewer; no menu calls it yet) need a review of their own.

### 3.6 Lookups outside the opened folder

A document names other files (an assembly its components, a drawing its
model) by a path stored on the machine that saved it. Neither the viewer nor
the service ever looks at a stored UNC path or a path on a mapped network
drive, so a document cannot make SolidSeas connect to a server it names
(`tests/test_resolve_safety.py`: `test_a_planted_unc_path_is_never_touched`,
`test_a_mapped_network_drive_is_never_touched`, `test_only_the_gateway_touches_the_filesystem`).
On a local fixed or removable drive, the viewer looks at a stored path outside
the opened folder once, each folder on its way looked at before the next is
used, and stops at a link or junction there (commit 18488c5:
`test_a_link_on_a_stored_paths_way_is_never_gone_through`,
`test_a_point_lookup_stops_at_a_folder_it_must_not_go_through`), so a crafted
document on such a drive cannot reach a share through a planted link; the
drawing editor's lookup does the same since finding 67. The service resolves
with lookups outside the roots off (finding 26). The setting "keep the
viewer's look for referenced files inside the opened folder"
(`references_inside_only`, commit 072919c) makes the viewer look nowhere
outside the opened folder at all, in its details, 3D view, prints, exports and
drawings (`tests/test_viewer_references_inside.py`).

### 3.7 Repeating the checks

```text
python -m pytest -q tests/test_occt_backend.py tests/test_extensions.py tests/test_viewer_extensions.py tests/test_viewer_convert.py tests/test_drawing_file_locate.py tests/test_resolve_safety.py tests/test_viewer_references_inside.py
```

Expected: every test passes; the tests that need Open CASCADE skip unless an
interpreter where OCP imports is found (`SOLIDSEAS_OCCT_PYTHON`).

```text
git grep -nE "helpers_per_worker=" -- src
git grep -nE "STEPCAFControl|IGESCAFControl|XCAF" -- src
git grep -n "solidseas-occt-" -- src
```

Expected: the first finds the service's pool (`serve/server.py`) and the
viewer's model pool (`viewer/modelpool.py`), each deciding it with the
backend's `helpers_per_worker`, and a docstring in `convert/occt.py`; the
second only a docstring in `solidseas_app/extensions/occt_helper.py`, so the
helper uses the basic readers; the third the two staging folders in
`convert/occt.py`, and no sweep (finding 59).

### 3.8 Recommendation

The helper's design holds the rules of `docs/OCCT.md` section 3: Open CASCADE
runs only out of process, with a memory cap, a time limit and no error box, on
a copy of the bytes SolidSeas read itself, and only what the core checked
comes back. Suitable on a managed PC with the conditions of 2.9, and in the
REST service with condition 7 of 1.8 (findings 59 to 61); serve IGES and BREP
only after the damaged files have been through it (finding 66).
