async def test_external_actor_crud(client):
    r = await client.post("/api/v1/actors", json={"handle": "ci", "name": "CI", "webhook_url": "http://ci/hook",
                                                  "webhook_secret": "s"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["kind"] == "external" and a["webhook_url"] == "http://ci/hook" and "webhook_secret" not in a
    r = await client.patch(f"/api/v1/actors/{a['id']}", json={"name": "CI2", "webhook_url": None})
    assert r.json()["name"] == "CI2" and r.json()["webhook_url"] is None
    handles = {x["handle"] for x in (await client.get("/api/v1/actors")).json()}
    assert {"you", "ci"} <= handles
    you = next(x for x in (await client.get("/api/v1/actors")).json() if x["handle"] == "you")
    assert (await client.delete(f"/api/v1/actors/{you['id']}")).status_code == 409
    assert (await client.delete(f"/api/v1/actors/{a['id']}")).status_code == 204
    assert (await client.post("/api/v1/actors", json={"handle": "you", "name": "dup"})).status_code == 409
