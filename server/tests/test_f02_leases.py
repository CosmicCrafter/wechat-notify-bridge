"""Protected claim leases, takeover fencing and independent restoration."""

import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from test_portal import portal as portal_fixture, ADMIN
from test_f02_receivers import protected, reply
from wechat_bridge.storage.database import Store

portal = portal_fixture


def test_two_concurrent_claims_have_one_winner_and_timeout_fences_old_report(portal):
    store, client, auth, *_ = portal
    cid, scoped, _ = protected(client, auth, "F02-lease", "租约")
    iid = reply(client, cid)
    url = "/api/inbox/" + str(iid)
    requests = [secrets.token_hex(16), secrets.token_hex(16)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda rid: client.post(
                    url + "/claim", headers=scoped, json={"request_id": rid, "lease_seconds": 30}
                ),
                requests,
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    first = next(r.json()["processing"] for r in results if r.status_code == 200)
    assert first["generation"] == 1
    store.db.execute("UPDATE inbox_claims SET lease_expires=0 WHERE inbox_id=?", (iid,))
    assert (
        client.post(
            url + "/renew", headers=scoped, json={"claim_id": first["claim_id"], "generation": 1}
        ).status_code
        == 409
    )
    stale = {
        "claim_id": first["claim_id"],
        "request_id": secrets.token_hex(16),
        "status": "completed",
        "result": "迟到结果",
        "generation": 1,
    }
    assert client.post(url + "/report", headers=scoped, json=stale).status_code == 409
    latest = client.post(
        url + "/claim",
        headers=scoped,
        json={"request_id": secrets.token_hex(16), "lease_seconds": 30},
    ).json()["processing"]
    assert latest["generation"] == 2
    assert client.post(url + "/report", headers=scoped, json=stale).status_code == 409
    done = {
        "claim_id": latest["claim_id"],
        "request_id": secrets.token_hex(16),
        "status": "completed",
        "result": "当前接收器完成",
        "generation": 2,
    }
    assert client.post(url + "/report", headers=scoped, json=done).status_code == 200
    assert client.post(url + "/report", headers=scoped, json=done).json()["duplicate"]
    assert store.claims.public(iid)["result"] == "当前接收器完成"
    assert [
        r[0]
        for r in store.db.execute(
            "SELECT action FROM inbox_claim_audit WHERE inbox_id=? ORDER BY id", (iid,)
        )
    ] == ["claim", "takeover", "completed"]


def test_live_renewal_survives_restart_and_wrong_generation_cannot_write(portal, tmp_path):
    store, client, auth, *rest = portal
    cid, scoped, _ = protected(client, auth, "F02-renew", "续期")
    iid = reply(client, cid)
    url = "/api/inbox/" + str(iid)
    claimed = client.post(
        url + "/claim",
        headers=scoped,
        json={"request_id": secrets.token_hex(16), "lease_seconds": 30},
    ).json()["processing"]
    current = {"claim_id": claimed["claim_id"], "generation": 1, "lease_seconds": 120}
    renewed = client.post(url + "/renew", headers=scoped, json=current).json()["processing"]
    assert renewed["lease_expires"] > claimed["lease_expires"]
    body = {
        "claim_id": claimed["claim_id"],
        "generation": 2,
        "request_id": secrets.token_hex(16),
        "status": "processing",
    }
    assert client.post(url + "/report", headers=scoped, json=body).status_code == 409
    db = sqlite3.connect(tmp_path / "restore.sqlite3")
    store.db.backup(db)
    db.close()
    copy = Store(tmp_path / "restore.sqlite3", rest[-1])
    try:
        assert copy.claims.public(iid) == store.claims.public(iid)
    finally:
        copy.close()


def test_legacy_claim_contract_and_encrypted_result_remain_compatible(portal):
    store, client, auth, _, chats, *_ = portal
    iid = reply(client, chats[0]["id"])
    url = "/api/inbox/" + str(iid)
    rid = secrets.token_hex(16)
    claimed = client.post(url + "/claim", headers=auth, json={"request_id": rid}).json()[
        "processing"
    ]
    assert claimed["generation"] == 0 and claimed["lease_expires"] is None
    body = {
        "claim_id": rid,
        "request_id": secrets.token_hex(16),
        "status": "completed",
        "result": "legacy-private-result",
    }
    assert client.post(url + "/report", headers=auth, json=body).status_code == 200
    assert client.post(url + "/report", headers=auth, json=body).json()["duplicate"]
    assert "legacy-private-result" not in "\n".join(store.db.iterdump())
