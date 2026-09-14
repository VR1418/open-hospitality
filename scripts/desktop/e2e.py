"""The owner's and the staff's walk through the real app, end to end.

Starts the app on its own books — the packaged build when given one, else this
checkout — and does what an owner would over a first month, through the same
API the screens use:

    set up the account and three hotels · turn modules on · ten staff a hotel
    · a month of night audits dropped in · codes confirmed with the practice
    AI · schedules built, copied and published · a GM signs in with a setup
    code and sees only their hotel · staff punch in and out at the time clock
    and see their week · a timecard approved · bank and card statements checked
    · the saved reports, AI memory notes and folders are there · backups armed

Every step is recorded; the run ends with a table and a non-zero exit if any
step failed. Nothing here touches a real install: the books live in a
temporary folder that is deleted afterwards unless --keep.

    uv run --extra desktop python scripts/desktop/e2e.py
    uv run --extra desktop python scripts/desktop/e2e.py --exe "dist/Open Hospitality/Open Hospitality.exe"
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from usali.desktop import demo  # noqa: E402
from usali.desktop.window import SingleInstance  # noqa: E402

LAST_NIGHT = date(2026, 9, 12)
DAYS = 30
OWNER_PASSWORD = "harbour lights at dusk"


@dataclass
class Report:
    rows: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return sum(1 for _, status, _ in self.rows if status == "FAILED")

    def table(self) -> str:
        width = max(len(name) for name, _, _ in self.rows)
        lines = [f"  {name.ljust(width)}  {status:<7} {note}" for name, status, note in self.rows]
        return "\n".join(lines)


REPORT = Report()


@contextmanager
def step(name: str) -> Iterator[list[str]]:
    notes: list[str] = []
    started = time.monotonic()
    print(f"-> {name}", flush=True)
    try:
        yield notes
    except Exception as exc:  # noqa: BLE001 — every failure is a row, the run goes on
        REPORT.rows.append((name, "FAILED", f"{type(exc).__name__}: {exc}"))
        print(f"   FAILED: {exc}", flush=True)
        traceback.print_exc()
    else:
        REPORT.rows.append((name, "ok", "; ".join(notes) + f" ({time.monotonic() - started:.0f}s)"))
        for note in notes:
            print(f"   {note}", flush=True)


class App:
    """The running app: its process, base URL and the first sign-in code."""

    def __init__(self, exe: Path | None, data_dir: Path) -> None:
        self.exe, self.data_dir = exe, data_dir
        self.base_url = ""
        self.code = ""
        self.process: subprocess.Popen[str] | None = None
        self.lines: list[str] = []

    def start(self) -> None:
        cmd = [str(self.exe)] if self.exe else [sys.executable, "-m", "usali.desktop.app"]
        cmd += ["--no-browser", "--no-tray"]
        env = {**os.environ, "OH_DATA_DIR": str(self.data_dir), "PYTHONIOENCODING": "utf-8"}
        self.process = subprocess.Popen(  # noqa: S603
            cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        found = threading.Event()

        def pump() -> None:
            assert self.process is not None and self.process.stdout is not None
            for line in self.process.stdout:
                self.lines.append(line.rstrip())
                m = re.search(r"(http://127\.0\.0\.1:\d+)\S*#code=(\S+)", line)
                if m and not found.is_set():
                    self.base_url, self.code = m.group(1), m.group(2)
                    found.set()

        threading.Thread(target=pump, name="app-output", daemon=True).start()
        if not found.wait(240):
            raise RuntimeError("the app did not print a sign-in code within four minutes:\n"
                               + "\n".join(self.lines[-30:]))

    def stop(self) -> None:
        if self.process is None:
            return
        SingleInstance.request_quit(self.data_dir / "system")
        try:
            self.process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=30)


class Owner:
    def __init__(self, base_url: str, token: str) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=120,
                                 headers={"Authorization": f"Bearer {token}"})

    def get(self, path: str, **params: object) -> httpx.Response:
        return self.http.get(path, params=params or None)

    def post(self, path: str, body: object = None, **kwargs: object) -> httpx.Response:
        return self.http.post(path, json=body, **kwargs)  # type: ignore[arg-type]

    def put(self, path: str, body: object) -> httpx.Response:
        return self.http.put(path, json=body)


def ok(r: httpx.Response, *codes: int) -> dict | list:  # type: ignore[type-arg]
    if r.status_code not in (codes or (200, 201)):
        raise AssertionError(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def wait_until(what: str, check: Callable[[], bool], seconds: float, every: float = 2.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(every)
    raise TimeoutError(f"gave up waiting {seconds:.0f}s for {what}")


def monday_after(day: date) -> date:
    return day + timedelta(days=(7 - day.weekday()) % 7 or 7)


def tiny_jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 140, 160)).save(buf, format="JPEG")
    return buf.getvalue()


# --- the walk ---------------------------------------------------------------------------

def run(exe: Path | None, keep: bool) -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="oh-e2e-"))
    print(f"books in {data_dir}")
    app = App(exe, data_dir)
    hotels: dict[str, str] = {}  # code -> property_id (the same, by construction)
    people: dict[str, dict[str, int]] = {}  # code -> name -> employee_id
    subjects: dict[str, str] = {}  # GM name -> subject
    owner: Owner | None = None
    try:
        with step("start the app") as notes:
            app.start()
            notes.append(f"{'packaged build' if exe else 'this checkout'} at {app.base_url}")
        if not app.base_url:
            return 1  # nothing else can run; the table below says why

        with step("set up the owner's account") as notes:
            r = httpx.post(f"{app.base_url}/api/desktop/setup/owner", json={
                "code": app.code, "full_name": "Priya Owner", "email": "owner@example.com",
                "password": OWNER_PASSWORD, "device_label": "e2e",
            }, timeout=60)
            body = ok(r, 201)
            owner = Owner(app.base_url, body["access_token"])
            notes.append("signed in; recovery code " + ("given" if body.get("recovery_code") else "absent"))
            recovery = body.get("recovery_code", "")

        assert owner is not None
        with step("set up three hotels") as notes:
            ok(owner.put("/api/desktop/welcome/group", {"name": "Redstone Hotel Group"}), 204)
            for h in demo.HOTELS:
                made = ok(owner.post("/api/desktop/welcome/property", {
                    "ownership_entity": h.entity, "name": h.name, "code": h.code,
                    "pms_source": h.pms, "timezone": "America/Chicago",
                    "wage_jurisdiction": "US-CA" if h.code == "SHI01" else "US",
                    "report_name": "" if h.pms == "SKYTOUCH" else h.name.upper(),
                    "fiscal": {"calendar_type": "calendar_month", "fiscal_year_start_month": 1,
                               "week_start_weekday": None},
                }), 201)
                hotels[h.code] = made["property_id"]
                assert made["property_id"] == h.code, made
            ok(owner.post("/api/desktop/welcome/finish"))
            notes.append(", ".join(hotels))

        with step("turn on Payroll & People and the AI helper") as notes:
            ok(owner.put("/api/desktop/modules", {"enabled": ["accounting", "payroll", "ai"]}))

            def settled() -> bool:
                try:
                    got = owner.get("/api/me/modules")
                    return got.status_code == 200 and not got.json().get("reloading")
                except httpx.HTTPError:
                    return False

            wait_until("the modules to reload", settled, 120)
            time.sleep(2)
            ok(owner.put("/api/desktop/ai", {"provider": "mock", "model": "practice",
                                             "cap": "10.00", "max_calls": 500}))
            notes.append("practice AI on")

        with step("ten staff at each hotel") as notes:
            for h in demo.HOTELS:
                depts = {d["name"]: d["department_id"]
                         for d in ok(owner.get("/api/departments", property=h.code))}
                people[h.code] = {}
                for p in demo.staff(h):
                    body = {"full_name": p.full_name, "property": h.code, "pay_type": p.pay_type,
                            "department_id": depts[p.department]}
                    if p.role:
                        body["role"] = p.role
                        body["email"] = p.full_name.lower().replace(" ", ".") + "@example.com"
                    made = ok(owner.post("/api/employees", body), 201)
                    people[h.code][p.full_name] = made["employee_id"]
                    if p.role:
                        subjects[p.full_name] = made["keycloak_subject"]
            notes.append(f"{sum(len(v) for v in people.values())} people, {len(subjects)} with a sign-in")

        with step("a month of night audits, dropped in") as notes:
            drop = data_dir / "Drop reports here"
            written = 0
            for h in demo.HOTELS:
                written += len(demo.write_reports(h, drop, LAST_NIGHT, DAYS))
            read = data_dir / "Reports we read"
            unreadable = data_dir / "Reports we couldn't read"
            wait_until("the intake to read every report",
                       lambda: not any(drop.glob("*.pdf")), 900, every=5)
            bad = sorted(p.name for p in unreadable.glob("*.pdf"))
            assert not bad, f"{len(bad)} unreadable: {bad[:3]}"
            got = len(list(read.glob("*.pdf")))
            assert got == written, f"{got} of {written} filed as read"
            notes.append(f"{written} reports read, none unreadable")

        with step("the books have last night's figures for every hotel") as notes:
            view = ok(owner.get("/api/desktop/portfolio"))
            for row in view["hotels"]:
                assert row["status"] == "in", (row["property_id"], row.get("note"))
                assert row["revenue"] not in (None, "0", "0.00"), row
            notes.append(f"{len(view['hotels'])} hotels in; group revenue {view['totals'].get('revenue')}")

        with step("the owner's breakeven per hotel, and the profit picture") as notes:
            for i, h in enumerate(demo.HOTELS):
                # One hotel gets a breakeven it cannot reach; the others one they can.
                annual = "9000000" if i == 0 else "120000"
                got = ok(owner.put(f"/api/desktop/hotels/{h.code}/targets",
                                   {"breakeven_annual": annual, "last_year_revenue": None}))
                assert got["breakeven_annual"] == f"{annual}.00" and got["changed_at"], got
            view = ok(owner.get("/api/desktop/portfolio"))
            summary = view["totals"]["breakeven"]
            assert summary["unset"] == 0 and summary["behind"] >= 1 and summary["above"] >= 1, summary
            for row in view["hotels"]:
                o = row["outlook"]
                assert o is not None and o["projected_year"] and o["projection_basis"] in ("run_rate", "last_year"), row
                # Rooms need a room count: choiceADVANTAGE prints one; AutoClerk and
                # OPERA hotels wait for the owner to type theirs (the checklist says so).
                if row["rooms_total"] is not None:
                    assert row["rooms_sold_month"] and row["rooms_available_month"], row
            assert any(f["kind"] == "behind_breakeven" for f in view["findings"]), view["findings"]
            assert view["totals"]["rooms_total"] and view["totals"]["rooms_sold"], view["totals"]
            one = ok(owner.get("/api/desktop/portfolio", property=demo.HOTELS[1].code))
            assert [r["property_id"] for r in one["hotels"]] == [demo.HOTELS[1].code]
            notes.append(f"{summary['above']} above breakeven, {summary['behind']} behind; "
                         f"{view['totals']['rooms_sold']} of {view['totals']['rooms_total']} rooms sold; one hotel narrows the page")

        with step("codes to confirm, with the practice AI's help") as notes:
            decided = 0
            for h in demo.HOTELS:
                codes = ok(owner.get("/api/desktop/codes", property=h.code))
                choices = ok(owner.get("/api/desktop/codes/choices", property=h.code))["lines"]
                for item in codes["items"]:
                    if item["status"] == "confirmed":
                        continue
                    # A code the dictionary already guesses is confirmed as it
                    # stands; only a code nothing decides is put to the AI —
                    # whose practice mode picks the first line it is offered.
                    line = None
                    if item.get("current") is None:
                        suggestion = owner.post("/api/desktop/ai/suggest", {
                            "property_id": h.code, "pms_source": h.pms, "code": item["code"],
                        })
                        line = suggestion.json().get("line") if suggestion.status_code == 200 else None
                    choice = item.get("current") or line or choices[0]
                    ok(owner.put(f"/api/desktop/codes/{item['code']}", {
                        "property_id": h.code, "pms_source": h.pms,
                        "line": {k: choice.get(k) for k in
                                 ("schedule_id", "major", "sub", "line_item", "gl_account_code")},
                        "origin": "ai-accepted" if line else "owner",
                    }))
                    decided += 1
            notes.append(f"{decided} codes decided")

        week1 = monday_after(date.today())
        week2 = week1 + timedelta(days=7)
        with step("schedules: built from the standard shifts, copied, published") as notes:
            shifts_made = 0
            for h in demo.HOTELS:
                tpl = {t["name"]: t for t in ok(owner.get("/api/desktop/rota/templates", property=h.code))}
                assert {"Morning desk", "Evening desk", "Night audit", "Housekeeping"} <= set(tpl)
                roster = [p for p in demo.staff(h)]
                desk = [people[h.code][p.full_name] for p in roster if p.department == "Front desk"]
                rooms = [people[h.code][p.full_name] for p in roster if p.department == "Housekeeping"]
                breakfast = [people[h.code][p.full_name] for p in roster if p.department == "Breakfast"]
                fixit = [people[h.code][p.full_name] for p in roster if p.department == "Maintenance"]
                week = ok(owner.post("/api/schedule/weeks", {"property": h.code, "week_start": week1.isoformat()}), 201)
                sid = week["schedule_id"]

                def place(day: date, t: dict, who: int | None) -> None:  # type: ignore[type-arg]
                    nonlocal shifts_made
                    ok(owner.post(f"/api/schedule/weeks/{sid}/shifts", {
                        "business_date": day.isoformat(), "department_id": t["department_id"],
                        "start_time": t["start_time"], "end_time": t["end_time"],
                        "crosses_midnight": t["crosses_midnight"], "employee_id": who,
                        "template_id": t["template_id"],
                    }), 201)
                    shifts_made += 1

                for i in range(7):
                    day = week1 + timedelta(days=i)
                    place(day, tpl["Morning desk"], desk[i % len(desk)])
                    place(day, tpl["Evening desk"], desk[(i + 1) % len(desk)])
                    place(day, tpl["Night audit"], desk[(i + 2) % len(desk)] if i % 3 else None)
                    for k, who in enumerate(rooms):
                        if (i + k) % 7 not in (5, 6):
                            place(day, tpl["Housekeeping"], who)
                    place(day, tpl["Breakfast"], breakfast[0])
                    if i < 5:
                        place(day, tpl["Maintenance"], fixit[0])
                copied = ok(owner.post("/api/desktop/rota/copy", {
                    "property": h.code, "from_week_start": week1.isoformat(),
                    "to_week_start": week2.isoformat(),
                }), 201)
                assert copied["copied"] > 0, copied
                ok(owner.post(f"/api/schedule/weeks/{sid}/publish"))
                ok(owner.post(f"/api/schedule/weeks/{copied['schedule_id']}/publish"))
                projection = ok(owner.get(f"/api/schedule/weeks/{sid}/projection"))
                assert projection["employees"], "no projected hours"
            notes.append(f"{shifts_made} shifts on the week of {week1}, copied to {week2}, both published")

        with step("a GM signs in with a setup code and sees only their hotel") as notes:
            gm_name, subject = next(iter(subjects.items()))
            gm_hotel = next(h for h in demo.HOTELS if any(p.full_name == gm_name for p in demo.staff(h)))
            other = next(h for h in demo.HOTELS if h.code != gm_hotel.code)
            given = ok(owner.post(f"/api/desktop/accounts/{subject}/setup-code"))
            login = gm_name.lower().replace(" ", ".") + "@example.com"
            signed = ok(httpx.post(f"{app.base_url}/api/desktop/setup-code", json={
                "login": login, "code": given["setup_code"], "new_password": "quiet harbour morning",
            }, timeout=60))
            gm = Owner(app.base_url, signed["access_token"])
            mine = gm.get("/api/schedule/weeks", property=gm_hotel.code, week_start=week1.isoformat())
            assert mine.status_code == 200, mine.text
            theirs = gm.get("/api/schedule/weeks", property=other.code, week_start=week1.isoformat())
            assert theirs.status_code == 403, theirs.text
            again = ok(httpx.post(f"{app.base_url}/api/desktop/signin", json={
                "login": login, "password": "quiet harbour morning"}, timeout=60))
            assert again["access_token"]
            notes.append(f"{gm_name}: own hotel 200, another hotel 403, password sign-in works")

        with step("staff punch in and out at the time clock and see their week") as notes:
            photo = tiny_jpeg()
            punched = 0
            for h in demo.HOTELS:
                device = ok(owner.post("/api/kiosk-devices", {"property": h.code, "name": f"{h.code} front desk iPad"}), 201)
                kiosk = httpx.Client(base_url=app.base_url, timeout=60,
                                     headers={"X-Kiosk-Token": device["token"]})
                roster = ok(kiosk.get("/api/kiosk/employees"))
                assert len(roster) >= 9, f"kiosk roster {len(roster)}"
                names = [p.full_name for p in demo.staff(h) if p.department == "Front desk"][:2]
                for name in names:
                    eid = people[h.code][name]
                    for punch_type in ("clock_in", "clock_out"):
                        r = kiosk.post("/api/kiosk/punch", data={"employee_id": str(eid), "punch_type": punch_type},
                                       files={"photo": ("punch.jpg", photo, "image/jpeg")})
                        ok(r, 201)
                        punched += 1
                    week = ok(kiosk.get("/api/kiosk/my-week",
                                        params={"employee_id": eid, "week_start": week1.isoformat()}))
                    assert week, "my week is empty"
            notes.append(f"{punched} punches at 3 time clocks; my-week answers")

        with step("the punches became timecards, approvable once the period ends") as notes:
            cards = ok(owner.get("/api/timecards"))
            assert cards, "no timecards after the punches"
            card = ok(owner.get(f"/api/timecards/{cards[0]['timecard_id']}"))
            punch_ids = [p["punch_id"] for d in card.get("days", []) for p in d.get("punches", [])]
            assert punch_ids, "the timecard shows no punches"
            approved = owner.post(f"/api/timecards/{cards[0]['timecard_id']}/approve",
                                  {"acknowledged_punch_ids": punch_ids})
            # Today's period is still running: approving it is rightly refused,
            # and the refusal says when it can be.
            if approved.status_code == 409:
                assert "still in progress" in approved.text, approved.text
                notes.append(f"{len(cards)} timecards; approval refused until the period ends, as it should be")
            else:
                ok(approved)
                notes.append(f"{len(cards)} timecards; {cards[0]['employee_name']}'s approved")

        with step("bank and card statements checked and sorted") as notes:
            summary = []
            for h in demo.HOTELS:
                bank_csv = demo.bank_statement_csv(h, demo.nights(h, LAST_NIGHT, DAYS))
                bank = ok(owner.post("/api/desktop/statements", data={
                    "property": h.code, "kind": "bank", "account_label": "Operating account"},
                    files={"file": ("bank.csv", bank_csv.encode(), "text/csv")}), 201)
                kinds = {r["match_kind"] for r in bank["rows"]}
                assert "settlement" in kinds and "payroll" in kinds, kinds
                # OPERA's dictionary has no cash code, so the desk's cash never
                # reaches the books and a cash deposit rightly stays unmatched.
                deposits = sum(1 for r in bank["rows"] if r["description"] == "DEPOSIT")
                if h.pms != "OPERA":
                    assert "cash" in kinds, kinds
                matched = sum(1 for r in bank["rows"] if r["match_kind"] in ("settlement", "cash"))
                credits = sum(1 for r in bank["rows"] if not r["amount"].startswith("-"))
                allowed = 2 + (deposits if h.pms == "OPERA" else 0)
                assert matched >= credits - allowed, f"{matched} of {credits} credits matched"
                card_csv = demo.card_statement_csv(h, LAST_NIGHT, DAYS)
                card = ok(owner.post("/api/desktop/statements", data={
                    "property": h.code, "kind": "card", "account_label": "Visa ending 4411"},
                    files={"file": ("card.csv", card_csv.encode(), "text/csv")}), 201)
                depot = next(r for r in card["rows"] if r["description"].startswith("HOME DEPOT"))
                ok(owner.put(f"/api/desktop/statements/lines/{depot['line_id']}", {"category": "Repairs & maintenance"}))
                summary.append(f"{h.code}: {matched}/{credits} credits matched, {bank['unmatched']} to look at")
            notes.extend(summary)

        with step("the saved reports, the AI memory notes and the folders are there") as notes:
            saved = data_dir / "Saved reports"
            wait_until("saved reports", lambda: len(list(saved.rglob("*.pdf"))) >= DAYS * 3 - 3, 240, every=5)
            pdfs, packs = len(list(saved.rglob("*.pdf"))), len(list(saved.rglob("*.xlsx")))
            memory = data_dir / "AI memory"
            wait_until("memory notes", lambda: len(list((memory / "Hotels").glob("*.md"))) == 3, 180, every=5)
            folders = ok(owner.get("/api/desktop/folders"))
            assert {f["id"] for f in folders["folders"]} >= {"saved", "drop", "read", "unreadable", "memory"}
            notes.append(f"{pdfs} daily summaries, {packs} accountant packs, 3 hotel notes, {len(folders['folders'])} folders")

        with step("the accountant pack and the profit and loss read") as notes:
            month = f"{LAST_NIGHT:%Y-%m}"
            for h in demo.HOTELS:
                pack = ok(owner.get("/api/cpa-pack", property=h.code, month=month))
                assert pack["sales"]["lines"], h.code
                sos = ok(owner.get("/api/sos", property=h.code, date=LAST_NIGHT.isoformat()))
                assert sos["total_operating_revenue"] not in (None, "0"), h.code
            notes.append("3 packs, 3 statements")

        with step("backups armed to a folder") as notes:
            folder = data_dir / "Backups"
            ok(owner.put("/api/desktop/backup", {"folder": str(folder)}))
            if recovery:
                ok(owner.post("/api/desktop/backup/arm", {"recovery_code": recovery}), 200, 204)
            status = ok(owner.get("/api/desktop/backup"))
            notes.append(f"folder set; armed={status.get('armed')}")

        with step("the AI helper's connection check, in practice mode") as notes:
            checked = ok(owner.post("/api/desktop/ai/test"))
            notes.append(f"{checked['model']} answered")

        with step("the app stops cleanly") as notes:
            app.stop()
            assert app.process is not None and app.process.returncode == 0, app.process.returncode if app.process else None
            notes.append("exit 0")
    finally:
        app.stop()
        print("\n" + REPORT.table())
        print(f"\n{len(REPORT.rows) - REPORT.failed} of {len(REPORT.rows)} steps passed.")
        if REPORT.failed:
            print("\nLast lines from the app:")
            print("\n".join(app.lines[-40:]))
        if keep or REPORT.failed:
            print(f"\nbooks kept in {data_dir}")
        else:
            shutil.rmtree(data_dir, ignore_errors=True)
    return 1 if REPORT.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, help="the packaged Open Hospitality.exe (default: this checkout)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary books afterwards")
    args = parser.parse_args()
    return run(args.exe, args.keep)


if __name__ == "__main__":
    raise SystemExit(main())
