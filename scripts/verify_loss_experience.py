"""Recompute a portfolio's loss experience with the standard library only (csv, Decimal, datetime):
the same cleaning policy as the pandas service, written a second time by hand. Prints one JSON
object per portfolio; --compare-url fetches the API's answer and diffs it, exit 1 on any mismatch.

    uv run python scripts/verify_loss_experience.py PF-03 [PF-07 ...] [--year 2023]
    uv run python scripts/verify_loss_experience.py --all --compare-url http://localhost:8010
"""

import argparse
import csv
import json
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
STATUSES = {"settled", "open", "declined", "withdrawn"}
EXCLUSIONS = (  # in the order the rules are applied; each counted on the rows still remaining
    "policies_duplicate_identical", "policies_duplicate_conflicting", "policies_unknown_asset",
    "policies_unparseable_date", "policies_expiry_not_after_inception", "policies_nonpositive_premium",
    "policies_no_fx_rate", "claims_duplicate_identical", "claims_duplicate_conflicting", "claims_bad_status",
    "orphan_claims", "claims_unparseable_date", "loss_outside_term", "negative_amounts", "claims_no_fx_rate")
DKK_TOL = Decimal("0.02")
RATIO_TOL = Decimal("0.0002")


def read(name):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_date(text):
    """ISO first, then day-first 'DD-MM-YYYY'; anything else is None."""
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    return None


def dedupe(rows, key, counts, label):
    """Identical duplicates collapse to one row; conflicting ones are all dropped."""
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    kept = []
    for group in groups.values():
        distinct = {tuple(sorted(r.items())) for r in group}
        if len(distinct) == 1:
            counts[f"{label}_duplicate_identical"] += len(group) - 1
            kept.append(group[0])
        else:
            counts[f"{label}_duplicate_conflicting"] += len(group)
    return kept


def load():
    """Apply the cleaning rules in the documented order; count each exclusion."""
    counts = Counter({k: 0 for k in EXCLUSIONS})
    fx = {(r["month"], r["currency"]): Decimal(r["rate_dkk_per_unit"]) for r in read("fx_rates.csv")}
    assets = {r["asset_id"]: r for r in read("assets.csv")}

    raw = read("policies.csv")
    for p in raw:
        p["peril"] = p["peril"].strip().lower()
    policies = {}
    for p in dedupe(raw, "policy_id", counts, "policies"):
        if p["asset_id"] not in assets:
            counts["policies_unknown_asset"] += 1
            continue
        p["inception"], p["expiry"] = parse_date(p["inception_date"]), parse_date(p["expiry_date"])
        if p["inception"] is None or p["expiry"] is None:
            counts["policies_unparseable_date"] += 1
            continue
        if p["expiry"] <= p["inception"]:
            counts["policies_expiry_not_after_inception"] += 1
            continue
        premium = Decimal(p["annual_premium"])
        if premium <= 0:
            counts["policies_nonpositive_premium"] += 1
            continue
        rate = fx.get((p["inception"].strftime("%Y-%m"), p["currency"]))
        if rate is None:
            counts["policies_no_fx_rate"] += 1
            continue
        p["premium_dkk"] = premium * rate
        p["portfolio_id"] = assets[p["asset_id"]]["portfolio_id"]
        policies[p["policy_id"]] = p

    claims = []
    for c in dedupe(read("claims.csv"), "claim_id", counts, "claims"):
        if c["status"] not in STATUSES:
            counts["claims_bad_status"] += 1
            continue
        policy = policies.get(c["policy_id"])
        if policy is None:
            counts["orphan_claims"] += 1
            continue
        loss = parse_date(c["loss_date"])  # reported_date feeds no figure, so it never excludes
        if loss is None:
            counts["claims_unparseable_date"] += 1
            continue
        if not policy["inception"] <= loss <= policy["expiry"]:
            counts["loss_outside_term"] += 1
            continue
        paid, reserve = Decimal(c["paid_amount"]), Decimal(c["reserve_amount"])
        if paid < 0 or reserve < 0:
            counts["negative_amounts"] += 1
            continue
        rate = fx.get((loss.strftime("%Y-%m"), c["currency"]))
        if rate is None:
            counts["claims_no_fx_rate"] += 1
            continue
        native = {"settled": paid, "open": paid + reserve}.get(c["status"], Decimal(0))
        c["incurred_dkk"] = native * rate
        c["policy"] = policy
        claims.append(c)
    return policies, claims, counts


def summarise(policies, claims):
    premium = sum((p["premium_dkk"] for p in policies), Decimal(0))
    incurred = sum((c["incurred_dkk"] for c in claims), Decimal(0))
    largest = max((c["incurred_dkk"] for c in claims), default=Decimal(0))
    return {
        "policy_count": len(policies),
        "earned_premium_dkk": float(round(premium, 2)),
        "incurred_loss_dkk": float(round(incurred, 2)),
        "loss_ratio": float(round(incurred / premium, 4)) if premium else None,
        "claim_count": len(claims),
        "largest_claim_dkk": float(round(largest, 2)),
    }


def loss_experience(portfolio_id, policies, claims, counts, year=None):
    pols = [p for p in policies.values() if p["portfolio_id"] == portfolio_id
            and (year is None or p["inception"].year == year)]
    ids = {p["policy_id"] for p in pols}
    clms = [c for c in claims if c["policy_id"] in ids]
    perils = {}
    for peril in sorted({p["peril"] for p in pols}):
        perils[peril] = summarise([p for p in pols if p["peril"] == peril],
                                  [c for c in clms if c["policy"]["peril"] == peril])
    return {"portfolio_id": portfolio_id, "perils": perils,
            "total": summarise(pols, clms), "excluded": dict(counts)}


def fetch(base_url, portfolio_id, year):
    url = f"{base_url.rstrip('/')}/portfolios/{portfolio_id}/loss-experience"
    if year is not None:
        url += f"?underwriting_year={year}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        body = json.load(resp)
    perils = body.get("perils", [])
    if isinstance(perils, list):
        perils = {p.get("peril"): p for p in perils}
    return {"perils": perils, "total": body.get("total", {})}


def diff(mine, theirs):
    """Return one line per mismatching field; counts exact, money and ratios within tolerance."""
    lines = []
    groups = [("total", mine["total"], theirs["total"])]
    for peril in sorted(set(mine["perils"]) | set(theirs["perils"])):
        groups.append((peril, mine["perils"].get(peril, {}), theirs["perils"].get(peril, {})))
    for name, a, b in groups:
        for field in ("policy_count", "earned_premium_dkk", "incurred_loss_dkk",
                      "loss_ratio", "claim_count", "largest_claim_dkk"):
            x, y = a.get(field, "missing"), b.get(field, "missing")
            if field.endswith("_count") or "missing" in (x, y) or None in (x, y):
                ok = x == y
            else:
                tol = RATIO_TOL if field == "loss_ratio" else DKK_TOL
                ok = abs(Decimal(str(x)) - Decimal(str(y))) <= tol
            if not ok:
                lines.append(f"  {name}.{field}: script={x} api={y}")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("portfolio_ids", nargs="*")
    ap.add_argument("--all", action="store_true", help="every portfolio in assets.csv")
    ap.add_argument("--year", type=int, help="underwriting year filter, applied to both sides")
    ap.add_argument("--compare-url", help="API base URL to diff against, e.g. http://localhost:8010")
    args = ap.parse_args()

    policies, claims, counts = load()
    ids = args.portfolio_ids
    if args.all:
        ids = sorted({p["portfolio_id"] for p in policies.values()})
    if not ids:
        ap.error("give portfolio ids or --all")

    failed = False
    for pid in ids:
        mine = loss_experience(pid, policies, claims, counts, args.year)
        print(json.dumps(mine))
        if args.compare_url:
            mismatches = diff(mine, fetch(args.compare_url, pid, args.year))
            failed |= bool(mismatches)
            print(f"{pid}: {'MISMATCH' if mismatches else 'match'}", file=sys.stderr)
            for line in mismatches:
                print(line, file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
