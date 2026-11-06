"""Getting back in from the server itself, when the website can't help (a forgotten password, a lost phone for
two-step sign-in). Only someone who can run commands on the Unraid server can use it, so it's safe to be powerful.

On Unraid (a terminal, or the container's Console):

    docker exec -it solstone python -m app.cli list
    docker exec -it solstone python -m app.cli reset-password <login>        # prints a new password
    docker exec -it solstone python -m app.cli two-step-off <login>
    docker exec -it solstone python -m app.cli make-admin <login>            # an existing login becomes an admin,
                                                                             # or a new admin login is made

Every change signs that login out everywhere and goes in the activity log ("Server console").
"""
from __future__ import annotations

import os
import secrets
import sys

USAGE = __doc__.split("On Unraid", 1)[1].split("Every change", 1)[0]


def _as_data_owner() -> None:
    """docker exec runs as root; the database belongs to Solstone's own user. Become that user first, so nothing
    is left owned by root that Solstone then can't write."""
    if os.name != "posix" or os.geteuid() != 0:
        return
    from .config import config
    try:
        st = os.stat(config.data_dir)
        os.setgid(st.st_gid)
        os.setuid(st.st_uid)
    except OSError:
        pass


def _user(name: str):
    from . import auth, db
    rows = db.q("SELECT id FROM users WHERE username=? COLLATE NOCASE", (name,))
    return auth.get_user(rows[0]["id"]) if rows else None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("Solstone recovery:" + USAGE)
        return 0
    _as_data_owner()
    from . import auth, db, twostep
    auth._init()
    twostep._init()
    cmd, args = argv[0], argv[1:]
    if cmd == "list":
        for u in auth.list_users():
            print(f"{u['username']:<24} {u['role']:<8} {'two-step' if twostep.is_on(u['id']) else ''}")
        return 0
    if not args:
        print(f"Which login? python -m app.cli {cmd} <login>")
        return 2
    name = args[0]
    u = _user(name)
    if cmd == "reset-password":
        if not u:
            print(f"No login called {name}. (python -m app.cli list shows them all)")
            return 1
        pw = secrets.token_urlsafe(12)
        auth.update_user(u.id, password=pw)
        twostep.forget_devices(u.id)
        auth.audit("Server console", None, "reset_password", u.username)
        print(f"New password for {u.username}: {pw}\nSign in with it, then change it (account menu → Change password).")
        return 0
    if cmd == "two-step-off":
        if not u:
            print(f"No login called {name}.")
            return 1
        twostep.turn_off(u.id)
        db.x("DELETE FROM sessions_auth WHERE user_id=?", (u.id,))
        auth.audit("Server console", None, "two_step_off", u.username)
        print(f"Two-step sign-in is off for {u.username}. Sign in with just the password, then turn it on again "
              "(account menu → Two-step sign-in).")
        return 0
    if cmd == "make-admin":
        if u:
            if u.role != "admin":
                auth.update_user(u.id, role="admin")
            auth.audit("Server console", None, "make_admin", u.username)
            print(f"{u.username} is an admin.")
            return 0
        pw = secrets.token_urlsafe(12)
        auth.create_user(name, pw, "admin")
        auth.audit("Server console", None, "make_admin", f"{name} (new)")
        print(f"New admin login {name}, password: {pw}\nSign in, then change the password.")
        return 0
    print(f"Don't know {cmd!r}." + USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
