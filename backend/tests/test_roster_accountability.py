"""
End-to-end tests for the roster + accountability system.

Covers:
  - Master roster: create students, version endpoint, bulk sync
  - Incident roster: claim flow (claim, takeover, release)
  - Batch accountability submit → rollup correctness
  - Missing students endpoint filtering
  - Rollup by_grade and by_staff breakdowns
  - Tenant isolation: accountability data is scoped per tenant
  - Alarm deactivation: no 500 when roster claims exist
"""
from __future__ import annotations

import io
import csv
import pytest
from fastapi.testclient import TestClient

HEADERS = {"X-API-Key": "test-api-key"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_school(client: TestClient, name: str, slug: str) -> None:
    resp = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug, "setup_pin": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _create_user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    resp = client.post(
        f"/{slug}/users",
        headers=HEADERS,
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["user_id"])


def _activate(client: TestClient, slug: str, *, user_id: int, message: str = "Lockdown") -> int:
    resp = client.post(
        f"/{slug}/alarm/activate",
        headers=HEADERS,
        json={"message": message, "user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    alert_id = data.get("current_alert_id")
    assert alert_id is not None, f"activate did not return current_alert_id: {data}"
    return int(alert_id)


def _deactivate(client: TestClient, slug: str, *, user_id: int) -> None:
    resp = client.post(
        f"/{slug}/alarm/deactivate",
        headers=HEADERS,
        json={"user_id": user_id},
    )
    assert resp.status_code == 200, resp.text


def _create_student(client: TestClient, slug: str, *, user_id: int, first: str, last: str, grade: str = "5") -> int:
    """Create a student in the master roster. Requires admin user (PERM_ROSTER_MANAGE)."""
    resp = client.post(
        f"/{slug}/roster/students",
        headers=HEADERS,
        params={"user_id": user_id},
        json={"first_name": first, "last_name": last, "grade_level": grade},
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["student_id"])


def _list_students(client: TestClient, slug: str, user_id: int) -> list[dict]:
    resp = client.get(
        f"/{slug}/roster/students",
        headers=HEADERS,
        params={"user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["students"]


def _roster_version(client: TestClient, slug: str, user_id: int) -> str:
    resp = client.get(
        f"/{slug}/roster/students/version",
        headers=HEADERS,
        params={"user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["version"]


def _claim(client: TestClient, slug: str, *, alert_id: int, student_id: int, user_id: int, status: str, takeover: bool = False) -> dict:
    resp = client.post(
        f"/{slug}/alerts/{alert_id}/roster/students/{student_id}/claim",
        headers=HEADERS,
        json={"user_id": user_id, "status": status, "takeover_confirmed": takeover},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _submit_accountability(client: TestClient, slug: str, *, alert_id: int, user_id: int, present: list[int], missing: list[int]) -> dict:
    resp = client.post(
        f"/{slug}/alerts/{alert_id}/accountability",
        headers=HEADERS,
        json={"user_id": user_id, "students_present": present, "students_missing": missing},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rollup(client: TestClient, slug: str, alert_id: int, user_id: int) -> dict:
    resp = client.get(
        f"/{slug}/alerts/{alert_id}/accountability/rollup",
        headers=HEADERS,
        params={"user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _missing(client: TestClient, slug: str, alert_id: int, user_id: int, *, include_unknown: bool = True) -> list[dict]:
    resp = client.get(
        f"/{slug}/alerts/{alert_id}/accountability/missing",
        headers=HEADERS,
        params={"user_id": user_id, "include_unknown": str(include_unknown).lower()},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["students"]


def _incident_roster(client: TestClient, slug: str, alert_id: int, user_id: int) -> dict:
    resp = client.get(
        f"/{slug}/alerts/{alert_id}/roster",
        headers=HEADERS,
        params={"user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Tests: Master Roster ──────────────────────────────────────────────────────

class TestMasterRoster:
    def test_create_and_list_students(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Roster School", "rsch")
        admin_id = _create_user(client, "rsch", name="Admin", role="admin")

        sid = _create_student(client, "rsch", user_id=admin_id, first="Alice", last="Smith", grade="3")
        assert sid > 0

        students = _list_students(client, "rsch", admin_id)
        names = [f"{s['first_name']} {s['last_name']}" for s in students]
        assert "Alice Smith" in names

    def test_roster_version_changes_after_add(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Version School", "vsch")
        admin_id = _create_user(client, "vsch", name="Admin", role="admin")

        v1 = _roster_version(client, "vsch", admin_id)
        _create_student(client, "vsch", user_id=admin_id, first="Bob", last="Jones", grade="4")
        v2 = _roster_version(client, "vsch", admin_id)

        assert v2 != v1, "version must change when roster is modified"

    def test_csv_import(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "CSV School", "csvsch")
        admin_id = _create_user(client, "csvsch", name="Admin", role="admin")

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["first_name", "last_name", "grade_level", "student_ref"])
        w.writerow(["Charlie", "Brown", "2", "CB001"])
        w.writerow(["Diana", "Prince", "3", "DP002"])

        # Step 1: preview
        preview_resp = client.post(
            "/csvsch/roster/students/import/preview",
            headers=HEADERS,
            params={"user_id": admin_id},
            files={"file": ("roster.csv", buf.getvalue().encode(), "text/csv")},
        )
        assert preview_resp.status_code == 200, preview_resp.text
        preview = preview_resp.json()
        assert preview["valid_count"] >= 2
        session_token = preview["session_token"]

        # Step 2: commit
        commit_resp = client.post(
            "/csvsch/roster/students/import/commit",
            headers=HEADERS,
            params={"user_id": admin_id},
            json={"session_token": session_token, "conflict_strategy": "skip"},
        )
        assert commit_resp.status_code == 200, commit_resp.text

        students = _list_students(client, "csvsch", admin_id)
        names = {f"{s['first_name']} {s['last_name']}" for s in students}
        assert "Charlie Brown" in names
        assert "Diana Prince" in names

    def test_archive_student(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Archive School", "asch")
        admin_id = _create_user(client, "asch", name="Admin", role="admin")

        sid = _create_student(client, "asch", user_id=admin_id, first="Eve", last="Arc", grade="5")
        students_before = _list_students(client, "asch", admin_id)
        assert any(s["student_id"] == sid for s in students_before)

        resp = client.delete(
            f"/asch/roster/students/{sid}",
            headers=HEADERS,
            params={"user_id": admin_id},
        )
        assert resp.status_code == 204, resp.text

        students_after = _list_students(client, "asch", admin_id)
        assert not any(s["student_id"] == sid for s in students_after)


# ── Tests: Incident Roster & Claims ──────────────────────────────────────────

class TestIncidentRoster:
    def test_claim_and_roster_reflects_status(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Claim School", "clsch")
        admin_id = _create_user(client, "clsch", name="Admin", role="admin")
        teacher_id = _create_user(client, "clsch", name="Ms. Smith", role="teacher")
        sid = _create_student(client, "clsch", user_id=admin_id, first="Frank", last="Oz", grade="6")

        alert_id = _activate(client, "clsch", user_id=admin_id)

        result = _claim(client, "clsch", alert_id=alert_id, student_id=sid, user_id=teacher_id, status="present_with_me")
        assert result["ok"] is True
        assert result["conflict"] is False

        roster = _incident_roster(client, "clsch", alert_id, teacher_id)
        found = next((r for r in roster["students"] if r["student_id"] == sid), None)
        assert found is not None
        assert found["claim"]["status"] == "present_with_me"

    def test_claim_conflict_and_takeover(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Conflict School", "cnsch")
        admin_id = _create_user(client, "cnsch", name="Admin", role="admin")
        t1 = _create_user(client, "cnsch", name="Teacher 1", role="teacher")
        t2 = _create_user(client, "cnsch", name="Teacher 2", role="teacher")
        sid = _create_student(client, "cnsch", user_id=admin_id, first="Grace", last="Lee", grade="2")

        alert_id = _activate(client, "cnsch", user_id=admin_id)
        _claim(client, "cnsch", alert_id=alert_id, student_id=sid, user_id=t1, status="present_with_me")

        # Second teacher tries to claim without takeover — gets conflict
        result2 = _claim(client, "cnsch", alert_id=alert_id, student_id=sid, user_id=t2, status="missing")
        assert result2["conflict"] is True

        # Takeover succeeds
        result3 = _claim(client, "cnsch", alert_id=alert_id, student_id=sid, user_id=t2, status="missing", takeover=True)
        assert result3["ok"] is True
        assert result3["conflict"] is False

        roster = _incident_roster(client, "cnsch", alert_id, t2)
        found = next(r for r in roster["students"] if r["student_id"] == sid)
        assert found["claim"]["status"] == "missing"

    def test_release_claim(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Release School", "relsch")
        admin_id = _create_user(client, "relsch", name="Admin", role="admin")
        teacher_id = _create_user(client, "relsch", name="Teacher", role="teacher")
        sid = _create_student(client, "relsch", user_id=admin_id, first="Henry", last="Ford", grade="4")

        alert_id = _activate(client, "relsch", user_id=admin_id)
        result = _claim(client, "relsch", alert_id=alert_id, student_id=sid, user_id=teacher_id, status="present_with_me")
        claim_id = result["claim"]["id"]

        resp = client.delete(
            f"/relsch/alerts/{alert_id}/roster/claims/{claim_id}",
            headers=HEADERS,
            params={"user_id": teacher_id},
        )
        assert resp.status_code == 204, resp.text

        roster = _incident_roster(client, "relsch", alert_id, teacher_id)
        found = next(r for r in roster["students"] if r["student_id"] == sid)
        assert found["claim"] is None


# ── Tests: Batch Accountability ───────────────────────────────────────────────

class TestBatchAccountability:
    def _setup(self, client: TestClient, login_super_admin, slug: str) -> tuple[int, int, list[int]]:
        """Returns (teacher_id, alert_id, [student_ids])."""
        login_super_admin()
        _create_school(client, f"Acct School {slug}", slug)
        admin_id = _create_user(client, slug, name="Admin", role="admin")
        teacher_id = _create_user(client, slug, name="Teacher", role="teacher")
        sids = [
            _create_student(client, slug, user_id=admin_id, first=f"S{i}", last="Test", grade=str((i % 5) + 1))
            for i in range(5)
        ]
        alert_id = _activate(client, slug, user_id=admin_id)
        return teacher_id, alert_id, sids

    def test_submit_returns_ok_with_counts(self, client: TestClient, login_super_admin) -> None:
        teacher_id, alert_id, sids = self._setup(client, login_super_admin, "acct1")
        result = _submit_accountability(
            client, "acct1",
            alert_id=alert_id, user_id=teacher_id,
            present=sids[:3], missing=sids[3:],
        )
        assert result["ok"] is True
        assert result["total"] == 5
        assert result["inserted"] + result["updated"] == 5

    def test_rollup_reflects_submitted_claims(self, client: TestClient, login_super_admin) -> None:
        teacher_id, alert_id, sids = self._setup(client, login_super_admin, "acct2")

        # All 5 students: 3 present, 2 missing
        _submit_accountability(
            client, "acct2",
            alert_id=alert_id, user_id=teacher_id,
            present=sids[:3], missing=sids[3:],
        )
        rollup = _rollup(client, "acct2", alert_id, teacher_id)
        assert rollup["total_students"] == 5
        assert rollup["accounted"] == 3  # present_with_me counts as accounted
        assert rollup["missing"] == 2
        assert rollup["unknown"] == 0
        assert rollup["percentage_accounted"] == pytest.approx(60.0, abs=1)

    def test_rollup_has_by_grade_breakdown(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Grade Rollup", "grrollup")
        admin_id = _create_user(client, "grrollup", name="Admin", role="admin")
        teacher_id = _create_user(client, "grrollup", name="Teacher", role="teacher")

        # Two grade-5 and one grade-3 student
        sid_a = _create_student(client, "grrollup", user_id=admin_id, first="A", last="X", grade="5")
        sid_b = _create_student(client, "grrollup", user_id=admin_id, first="B", last="Y", grade="5")
        sid_c = _create_student(client, "grrollup", user_id=admin_id, first="C", last="Z", grade="3")

        alert_id = _activate(client, "grrollup", user_id=admin_id)
        _submit_accountability(
            client, "grrollup",
            alert_id=alert_id, user_id=teacher_id,
            present=[sid_a, sid_b, sid_c], missing=[],
        )

        rollup = _rollup(client, "grrollup", alert_id, teacher_id)
        by_grade = {g["grade_level"]: g for g in rollup["by_grade"]}
        assert by_grade["5"]["total"] == 2
        assert by_grade["5"]["accounted"] == 2
        assert by_grade["3"]["total"] == 1
        assert by_grade["3"]["accounted"] == 1

    def test_rollup_has_by_staff_breakdown(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Staff Rollup", "srrollup")
        admin_id = _create_user(client, "srrollup", name="Admin", role="admin")
        t1 = _create_user(client, "srrollup", name="Ms. Alpha", role="teacher")
        t2 = _create_user(client, "srrollup", name="Mr. Beta", role="teacher")

        sids = [_create_student(client, "srrollup", user_id=admin_id, first=f"Kid{i}", last="R", grade="4") for i in range(4)]
        alert_id = _activate(client, "srrollup", user_id=admin_id)

        # t1 claims 2 present, t2 claims 2 missing
        _submit_accountability(client, "srrollup", alert_id=alert_id, user_id=t1, present=sids[:2], missing=[])
        _submit_accountability(client, "srrollup", alert_id=alert_id, user_id=t2, present=[], missing=sids[2:])

        rollup = _rollup(client, "srrollup", alert_id, t1)
        by_staff = {s["staff_label"]: s for s in rollup["by_staff"]}
        assert "Ms. Alpha" in by_staff
        assert "Mr. Beta" in by_staff
        assert by_staff["Ms. Alpha"]["accounted"] == 2
        assert by_staff["Mr. Beta"]["missing"] == 2

    def test_empty_submit_is_noop(self, client: TestClient, login_super_admin) -> None:
        teacher_id, alert_id, sids = self._setup(client, login_super_admin, "acct3")
        result = _submit_accountability(
            client, "acct3",
            alert_id=alert_id, user_id=teacher_id,
            present=[], missing=[],
        )
        assert result["ok"] is True
        assert result["total"] == 0

    def test_resubmit_updates_existing_claims(self, client: TestClient, login_super_admin) -> None:
        teacher_id, alert_id, sids = self._setup(client, login_super_admin, "acct4")

        # First: mark all present
        _submit_accountability(client, "acct4", alert_id=alert_id, user_id=teacher_id, present=sids, missing=[])
        r1 = _rollup(client, "acct4", alert_id, teacher_id)
        assert r1["accounted"] == 5

        # Then: flip first two to missing
        _submit_accountability(client, "acct4", alert_id=alert_id, user_id=teacher_id, present=sids[2:], missing=sids[:2])
        r2 = _rollup(client, "acct4", alert_id, teacher_id)
        assert r2["missing"] == 2
        assert r2["accounted"] == 3


# ── Tests: Missing Students Endpoint ─────────────────────────────────────────

class TestMissingStudents:
    def test_missing_endpoint_excludes_accounted(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Missing School", "missch")
        admin_id = _create_user(client, "missch", name="Admin", role="admin")
        teacher_id = _create_user(client, "missch", name="Teacher", role="teacher")

        present_sid = _create_student(client, "missch", user_id=admin_id, first="Present", last="Kid", grade="3")
        missing_sid = _create_student(client, "missch", user_id=admin_id, first="Missing", last="Kid", grade="4")
        _create_student(client, "missch", user_id=admin_id, first="Unknown", last="Kid", grade="5")  # unclaimed

        alert_id = _activate(client, "missch", user_id=admin_id)
        _submit_accountability(
            client, "missch",
            alert_id=alert_id, user_id=teacher_id,
            present=[present_sid], missing=[missing_sid],
        )

        # include_unknown=true → missing + unknown
        students = _missing(client, "missch", alert_id, teacher_id, include_unknown=True)
        sids = {s["student_id"] for s in students}
        assert present_sid not in sids
        assert missing_sid in sids

        # include_unknown=false → only explicitly missing
        only_missing = _missing(client, "missch", alert_id, teacher_id, include_unknown=False)
        only_sids = {s["student_id"] for s in only_missing}
        assert missing_sid in only_sids
        assert present_sid not in only_sids

    def test_missing_endpoint_grade_filter(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Grade Filter School", "gfsch")
        admin_id = _create_user(client, "gfsch", name="Admin", role="admin")
        teacher_id = _create_user(client, "gfsch", name="Teacher", role="teacher")

        sid_g3 = _create_student(client, "gfsch", user_id=admin_id, first="G3", last="Kid", grade="3")
        sid_g4 = _create_student(client, "gfsch", user_id=admin_id, first="G4", last="Kid", grade="4")

        alert_id = _activate(client, "gfsch", user_id=admin_id)
        _submit_accountability(client, "gfsch", alert_id=alert_id, user_id=teacher_id, present=[], missing=[sid_g3, sid_g4])

        resp = client.get(
            f"/gfsch/alerts/{alert_id}/accountability/missing",
            headers=HEADERS,
            params={"user_id": teacher_id, "grade_level": "3"},
        )
        assert resp.status_code == 200, resp.text
        students = resp.json()["students"]
        grades = {s["grade_level"] for s in students}
        assert grades == {"3"}


# ── Tests: Tenant Isolation ───────────────────────────────────────────────────

class TestAccountabilityTenantIsolation:
    def test_rollup_is_scoped_per_tenant(self, client: TestClient, login_super_admin) -> None:
        login_super_admin()
        _create_school(client, "Tenant A", "tnta")
        _create_school(client, "Tenant B", "tntb")

        admin_a = _create_user(client, "tnta", name="Admin A", role="admin")
        admin_b = _create_user(client, "tntb", name="Admin B", role="admin")
        teacher_a = _create_user(client, "tnta", name="Teacher A", role="teacher")

        sid = _create_student(client, "tnta", user_id=admin_a, first="Isolated", last="Kid", grade="5")

        alert_a = _activate(client, "tnta", user_id=admin_a)
        _activate(client, "tntb", user_id=admin_b)

        _submit_accountability(client, "tnta", alert_id=alert_a, user_id=teacher_a, present=[sid], missing=[])
        rollup_a = _rollup(client, "tnta", alert_a, teacher_a)
        assert rollup_a["total_students"] == 1
        assert rollup_a["accounted"] == 1

        # Tenant B has 0 students → rollup should show empty
        latest_b_resp = client.get(f"/tntb/alerts", headers=HEADERS, params={"limit": 1})
        assert latest_b_resp.status_code == 200
        alerts_b = latest_b_resp.json()["alerts"]
        if alerts_b:
            rollup_b = _rollup(client, "tntb", alerts_b[0]["alert_id"], admin_b)
            assert rollup_b["total_students"] == 0, "tenant B must not see tenant A students"


# ── Tests: Alarm deactivation + roster ────────────────────────────────────────

class TestAlarmDeactivationWithRoster:
    def test_deactivation_succeeds_when_claims_exist(self, client: TestClient, login_super_admin) -> None:
        """Deactivating while accountability claims exist must not raise a 500."""
        login_super_admin()
        _create_school(client, "Deact School", "deactsch")
        admin_id = _create_user(client, "deactsch", name="Admin", role="admin")
        teacher_id = _create_user(client, "deactsch", name="Teacher", role="teacher")
        sid = _create_student(client, "deactsch", user_id=admin_id, first="Student", last="X", grade="3")

        alert_id = _activate(client, "deactsch", user_id=admin_id)
        _submit_accountability(
            client, "deactsch",
            alert_id=alert_id, user_id=teacher_id,
            present=[sid], missing=[],
        )

        # Deactivate — must not fail
        _deactivate(client, "deactsch", user_id=admin_id)

        # Alarm is now off
        resp = client.get("/deactsch/alarm/status", headers=HEADERS)
        assert resp.json()["is_active"] is False

    def test_accountability_report_available_after_deactivation(self, client: TestClient, login_super_admin) -> None:
        """Historical rollup must still be queryable after the alarm ends."""
        login_super_admin()
        _create_school(client, "History School", "histsch")
        admin_id = _create_user(client, "histsch", name="Admin", role="admin")
        teacher_id = _create_user(client, "histsch", name="Teacher", role="teacher")
        sids = [_create_student(client, "histsch", user_id=admin_id, first=f"Kid{i}", last="H", grade="4") for i in range(3)]

        alert_id = _activate(client, "histsch", user_id=admin_id)
        _submit_accountability(
            client, "histsch",
            alert_id=alert_id, user_id=teacher_id,
            present=sids[:2], missing=sids[2:],
        )
        _deactivate(client, "histsch", user_id=admin_id)

        # Rollup is still available after deactivation
        rollup = _rollup(client, "histsch", alert_id, teacher_id)
        assert rollup["total_students"] == 3
        assert rollup["accounted"] == 2
        assert rollup["missing"] == 1
