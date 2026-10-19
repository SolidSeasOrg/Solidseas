"""A stand-in for ssh in the tunnel tests (``tests/test_gridfinity.py``): run as ``python
fake_ssh.py <ssh's arguments>``, it does what ``ssh -N -L 127.0.0.1:P:127.0.0.1:Q host`` does
for SolidSeas, listening on 127.0.0.1:P, except that it forwards each connection to
127.0.0.1:$FAKE_SSH_TARGET, the test's Tracefinity, since both ends are on this machine.

It writes the arguments it was given to $FAKE_SSH_ARGS (a file) and, with $FAKE_SSH_FAIL
set, prints that text to standard error and exits 255 the way ssh does when it cannot sign
in."""

import os
import socket
import sys
import threading


def pump(source: socket.socket, sink: socket.socket) -> None:
    try:
        while data := source.recv(65536):
            sink.sendall(data)
    except OSError:
        pass
    finally:
        for s in (source, sink):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def main() -> int:
    args = sys.argv[1:]
    if os.environ.get("FAKE_SSH_ARGS"):
        with open(os.environ["FAKE_SSH_ARGS"], "w", encoding="utf-8") as f:
            f.write("\n".join(args))
    if os.environ.get("FAKE_SSH_FAIL"):
        print(os.environ["FAKE_SSH_FAIL"], file=sys.stderr, flush=True)
        return 255
    spec = args[args.index("-L") + 1]
    bind, port = spec.split(":")[0], int(spec.split(":")[1])
    target = int(os.environ["FAKE_SSH_TARGET"])
    server = socket.socket()
    if os.name != "nt":  # as ssh does: the port of a tunnel just closed binds again
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((bind, port))
    server.listen()
    while True:
        client, _ = server.accept()
        try:
            upstream = socket.create_connection(("127.0.0.1", target))
        except OSError:  # ssh: "channel open failed"; the tunnel stays, the connection closes
            client.close()
            continue
        for a, b in ((client, upstream), (upstream, client)):
            threading.Thread(target=pump, args=(a, b), daemon=True).start()


if __name__ == "__main__":
    sys.exit(main())
