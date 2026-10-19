# Security policy

SolidSeas reads files that may come from anyone, and some parts of it answer
requests from other programs. We take reports about either seriously and are
grateful for them.

## Reporting a vulnerability

Please report security problems privately, not in a public issue, pull request
or discussion.

Use GitHub's private vulnerability reporting: open the repository's
**Security** tab and choose **Report a vulnerability**, or go straight to
<https://github.com/SolidSeas/SolidSeas/security/advisories/new>.
Only the maintainers can see the report.

A helpful report includes:

- the SolidSeas version and your operating system;
- which part is affected (see the scope below);
- steps to reproduce, ideally with a small file you made yourself that shows
  the problem (never send a confidential CAD file);
- what an attacker could achieve, as far as you know.

We aim to acknowledge a report within a week and to keep you updated as we
work on a fix. Once a fix is released we publish an advisory and, if you would
like, credit you for the find.

## Supported versions

SolidSeas is pre-1.0. Security fixes go into the latest release only, so please
check that a problem still happens there before reporting it.

| Version | Supported |
|---|---|
| Latest release | Yes |
| Anything older | No |

## Scope

These are the parts where a weakness matters most:

- **The readers of untrusted files.** Every reader of SOLIDWORKS documents and
  of the other 3D formats SolidSeas opens (STL, 3MF, OBJ, PLY, OFF, glTF, GLB,
  AMF, Parasolid, STEP, ACIS SAB, Alibre and the rest). A crafted file that
  makes SolidSeas crash in an unhandled way, hang, use unbounded memory, write
  anywhere, or run code is in scope.
- **The local REST service** (`solidseas serve`), including its token handling,
  its roots and path checks, its limits and the optional catalog.
- **The MCP server** (`docs/MCP.md`), including anything that lets a chat client
  reach past the rules the modeling assistant keeps.
- **Extension packages** (`docs/EXTENSIONS.md`): how a package is checked,
  added, switched on and run.

Also in scope: anything that makes SolidSeas write to, lock or change a source
CAD file when it should not, and anything that sends paths, property values or
other document data off the machine where the documentation says it stays.

Out of scope: problems in SOLIDWORKS itself, in a slicer or another program
SolidSeas hands a file to, or in third-party dependencies (please report those
upstream, though we are glad to hear about them too).

## Further reading

`docs/SECURITY_REVIEW.md` is our own security review, written for an
administrator deciding whether SolidSeas may run on a managed machine. It lists
the findings so far, their status and the tests that check them.
