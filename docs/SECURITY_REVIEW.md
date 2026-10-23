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
| 2 | The desktop app: the AI connector, the script runner, the SOLIDWORKS bridge and the machine policy (Phase 5) | Comes with Phase 5, as `docs/ROADMAP.md` says |

Apart from `solidseas serve`, the library and the command line open no socket
and start no process other than their own worker processes. Section 1.3 shows
the evidence, because the service is built on them.

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

### 1.2 What the service is

- One Python process (the server) and a fixed number of worker processes, one
  per CPU and at most 4 by default. Standard library only, plus `olefile` for
  legacy documents. Nothing is downloaded, compiled or loaded at run time.
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
| Workers end with the service | Verified, this review: stopping the service's process ended its workers. On Windows they share a Job Object with kill-on-close; on Linux each asks for `SIGKILL` when its parent dies (by inspection, finding 3) |

What will show up anyway, and is not the service's own connection: when a root
is a folder on a file share, Windows' or Linux's SMB client connects to that
server, as the service's account, to read the files. Only roots the
administrator configures are read that way.

### 1.4 What runs

- No `subprocess`, `os.system`, `shell=True`, `eval`, `exec`, `pickle` or
  `marshal` anywhere in `src/solidseas`. Verified by the grep in 1.7.
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
  the other formats' parsers run in the workers too (section 1.9).
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
registry. It never prints or logs a token.
No credentials of any kind are requested, used or stored besides its own
bearer tokens and identity key, and it never authenticates to anything.

### 1.7 Repeating the checks

From a checkout, with the development dependencies installed:

```text
python -m pytest -q tests/test_serve_security.py tests/test_serve_identity.py tests/test_serve.py tests/test_workers.py tests/test_resolve_safety.py tests/test_hardening.py tests/test_formats_core.py tests/test_formats_mesh_hostile.py tests/test_formats_step_hostile.py tests/test_formats_alibre_hostile.py
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
git grep -nE "\bsubprocess\b|os\.system|os\.popen|shell=True|import pickle|pickle\.loads|\bmarshal\b|\beval\(|\bexec\(" -- src/solidseas ":!src/solidseas/swapi"
```

Expected: nothing. The SOLIDWORKS bridge's client, `src/solidseas/swapi`,
starts `SolidSeas.SwBridge.exe` (`bridge.py`) and the C# compiler that builds
it (`build.py`) with `subprocess`, from an argument list and never through a
shell, for conversion on a Windows desktop; the service never imports it, and
section 2 will review the bridge.

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
six conditions:

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

Comes with Phase 5. `docs/ROADMAP.md` lists what that section must cover: the
AI connector, the script runner, the SOLIDWORKS bridge, what the app stores,
and the machine policy.

The AI connector and the machine policy exist now (provisional, `docs/API.md`
3.23). Two searches already show their chokepoints, and
`tests/test_ai_factory.py` repeats both on every test run (the first through
Python's syntax tree, so an alias or a call through a table is caught too):

```text
git grep -nE "(Anthropic|OpenAI|Gemini|Ollama|Noop)Provider\b|(CLOUD|LOCAL)_PROVIDERS|(\.|import )providers\b" -- src ":!src/solidseas/ai/providers" ":!src/solidseas/ai/factory.py"
git grep -nE "\bstart_run\(" -- src
```

Expected: the first looks everywhere but the providers' own package and
`src/solidseas/ai/factory.py`, which builds them (the cloud providers through
its `CLOUD_PROVIDERS` table), and finds only the package notes in
`src/solidseas/ai/__init__.py` and `src/solidseas/ai/fake.py` importing the
shared base class `ChatProvider` for the test stand-in, so nothing else names
a provider class or table or imports the package. The earlier search, for
`AnthropicProvider(` and the like, missed a call through a table and an aliased
import. The second finds only the definition in
`src/solidseas_app/assistant/automatic.py`. Behind the search, a provider
checks the machine policy itself before every call and health check, from its
own kind and address, so one built some other way still could not reach a
cloud provider under `LocalProviderOnly`.

The app reads the policy key and never writes it, except through
`SolidSeasViewer.exe --set-policy` (`src/solidseas_app/setpolicy.py`), which an
administrator runs elevated as a step of its own, with no Qt and no document
opened (`docs/ASSISTANT.md`, "Machine policy"). A third search shows it, and
`tests/test_set_policy.py` repeats it on every test run through Python's syntax
tree:

```text
git grep -nE "\b(CreateKey|CreateKeyEx|DeleteKey|DeleteKeyEx|DeleteValue|SetValue|SetValueEx|SaveKey|LoadKey|RegCreateKeyExW|RegSetValueExW|RegSetKeyValueW|RegDeleteKeyExW|RegDeleteValueW|RegDeleteTreeW)\b" -- src
```

Expected: two files. `src/solidseas_app/setpolicy.py`, whose `WindowsPolicyKey`
opens the key in the same 64-bit view the reader uses, and
`src/solidseas/swapi/hkcu.py`, which writes nothing but SOLIDWORKS' own settings
under `HKEY_CURRENT_USER\Software\SolidWorks` (its `WinRegistry` refuses any other
key) after a batch conversion, never the policy key.
