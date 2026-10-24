"""
Manage who can sign in to the dashboard: Gram Panchayat officials and NGO staff.

Run from the project root:
    python -m backend.app.jobs.officials add 9876543210 "Ujire GP secretary" --district "Dakshina Kannada" --taluk Belthangady
    python -m backend.app.jobs.officials add 9123456780 "Red Cross Udupi" --role ngo --district Udupi
    python -m backend.app.jobs.officials add 9000011111 "State control room"          (no area: all of Karnataka)
    python -m backend.app.jobs.officials taluks "Dakshina Kannada"                    (list taluk names)
    python -m backend.app.jobs.officials list
    python -m backend.app.jobs.officials remove 9876543210

Gram Panchayat (gp): sees their taluk, drafts/edits/approves its alerts, sees each family's report there.
NGO (ngo):           sees risk, approved alerts and evacuation counts in their district (or the state);
                     cannot approve alerts and never sees families' phone numbers.
Villagers don't need to be added: they sign in themselves on the villager page to report status.
Removing someone also signs them out everywhere.
"""
import argparse

from .. import areas, auth, database


def resolve_taluk(name: str, district: str | None) -> str:
    found = areas.get().find_taluk(name, district)
    if len(found) == 1:
        return found[0]["taluk_id"]
    if not found:
        raise SystemExit(f"error: no taluk called '{name}'" + (f" in {district}" if district else "")
                         + ". See the names with: python -m backend.app.jobs.officials taluks \"<district>\"")
    raise SystemExit("error: several taluks match; add --district. " +
                     ", ".join(f"{t['name']} ({t['district']})" for t in found))


def main() -> None:
    p = argparse.ArgumentParser(description="Manage dashboard sign-in for Gram Panchayat and NGO staff.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="allow a phone number to sign in")
    a.add_argument("phone")
    a.add_argument("name", help='name shown on approvals, e.g. "Ujire GP secretary" or "Red Cross Udupi"')
    a.add_argument("--role", choices=auth.ROLES, default="gp", help="gp (default) or ngo")
    a.add_argument("--district", help="district name, e.g. \"Dakshina Kannada\"")
    a.add_argument("--taluk", help="taluk name (Gram Panchayat officials), e.g. Belthangady")
    t = sub.add_parser("taluks", help="list taluks (of one district, or all)")
    t.add_argument("district", nargs="?")
    sub.add_parser("list", help="show everyone who can sign in")
    r = sub.add_parser("remove", help="stop a phone number signing in")
    r.add_argument("phone")
    args = p.parse_args()

    database.init_db()
    ar = areas.get()
    try:
        if args.cmd == "add":
            district = None
            if args.district:
                district = ar.find_district(args.district)
                if not district:
                    raise SystemExit(f"error: no district called '{args.district}'. Districts: "
                                     + ", ".join(d["name"] for d in ar.districts))
            taluk_id = resolve_taluk(args.taluk, district) if args.taluk else None
            if args.role == "gp" and not taluk_id:
                print("note: no --taluk given, so this Gram Panchayat login covers all of Karnataka.")
            o = auth.add_official(args.phone, args.name, args.role, taluk_id=taluk_id, district=district)
            print(f"added: {o['name']} ({o['phone']}) as {'Gram Panchayat' if o['role'] == 'gp' else 'NGO'}, "
                  f"area: {o['area']}")
        elif args.cmd == "taluks":
            for d in ar.districts:
                if args.district and d["name"].lower() != (ar.find_district(args.district) or "").lower():
                    continue
                print(f"{d['name']} ({d['name_kn']}): " + ", ".join(t["name"] for t in d["taluks"]))
        elif args.cmd == "remove":
            print("removed" if auth.remove_official(args.phone) else "no such person")
        else:
            rows = auth.list_officials()
            if not rows:
                print('nobody yet. Add someone with: python -m backend.app.jobs.officials add <phone> "<name>" --taluk <taluk>')
            for o in rows:
                print(f"  {o['role'].upper():<4} {o['phone']}  {o['name']:<28} {o['area']}   (added {o['created_at'][:10]})")
    except auth.AuthError as err:
        raise SystemExit(f"error: {err}")


if __name__ == "__main__":
    main()
