"""
Manage who can sign in to the dashboard: Gram Panchayat officials and NGO staff.

Run from the project root:
    python -m backend.app.jobs.officials add 9876543210 "Ujire GP secretary"            (Gram Panchayat)
    python -m backend.app.jobs.officials add 9123456780 "Red Cross Belthangady" --role ngo
    python -m backend.app.jobs.officials list
    python -m backend.app.jobs.officials remove 9876543210

Gram Panchayat (gp): sees everything, drafts/edits/approves alerts, sees each family's report.
NGO (ngo):           sees risk, approved alerts and evacuation counts per village; cannot approve
                     alerts and never sees families' phone numbers.
Villagers don't need to be added: they sign in themselves on the villager page to report status.
Removing someone also signs them out everywhere.
"""
import argparse

from .. import auth, database


def main() -> None:
    p = argparse.ArgumentParser(description="Manage dashboard sign-in for Gram Panchayat and NGO staff.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="allow a phone number to sign in")
    a.add_argument("phone")
    a.add_argument("name", help='name shown on approvals, e.g. "Ujire GP secretary" or "Red Cross Belthangady"')
    a.add_argument("--role", choices=auth.ROLES, default="gp", help="gp (default) or ngo")
    sub.add_parser("list", help="show everyone who can sign in")
    r = sub.add_parser("remove", help="stop a phone number signing in")
    r.add_argument("phone")
    args = p.parse_args()

    database.init_db()
    try:
        if args.cmd == "add":
            o = auth.add_official(args.phone, args.name, args.role)
            print(f"added: {o['name']} ({o['phone']}) as {'Gram Panchayat' if o['role'] == 'gp' else 'NGO'}")
        elif args.cmd == "remove":
            print("removed" if auth.remove_official(args.phone) else "no such person")
        else:
            rows = auth.list_officials()
            if not rows:
                print('nobody yet. Add someone with: python -m backend.app.jobs.officials add <phone> "<name>"')
            for o in rows:
                print(f"  {o['role'].upper():<4} {o['phone']}  {o['name']}   (added {o['created_at'][:10]})")
    except auth.AuthError as err:
        raise SystemExit(f"error: {err}")


if __name__ == "__main__":
    main()
