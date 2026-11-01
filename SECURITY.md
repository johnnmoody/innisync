# Security

InniSync runs a small web server on your own computer (127.0.0.1) and talks to your Y1 over adb, which on the Y1 is a
root shell. Problems in either can matter, so please report them privately:
[open a security advisory](https://github.com/johnnmoody/innisync/security/advisories/new).

Things worth reporting include another website or another program on the computer reaching InniSync's server,
anything that leaves the Y1's Wi-Fi adb open to the network, a file path that escapes the folder it should stay in,
and passwords or tokens showing up somewhere they shouldn't (logs, command lines, files outside the Keychain).

Fixes go into the latest release only.
