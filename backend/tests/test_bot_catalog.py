from openbot.bots.catalog import CATALOG, CATALOG_BY_ID, BotCatalogEntry, load_instructions


def test_catalog_entries_have_instruction_files():
    assert len(CATALOG) == 5
    assert len(CATALOG_BY_ID) == len(CATALOG)
    for raw in CATALOG:
        entry = BotCatalogEntry.model_validate(raw)
        assert load_instructions(entry)
        assert entry.handle == entry.instruction_file.removesuffix('.md')


async def test_catalog_list_install_duplicate_and_unknown(client):
    entries = (await client.get('/api/v1/bots/catalog')).json()
    assert {entry['id'] for entry in entries} == {
        'chief_of_staff', 'engineer', 'reviewer', 'qa', 'frontend_designer',
    }
    installed = await client.post('/api/v1/bots/catalog/engineer/install')
    assert installed.status_code == 201, installed.text
    assert installed.json()['instructions']
    assert installed.json()['load_repository_instructions'] is True
    assert (await client.post('/api/v1/bots/catalog/engineer/install')).status_code == 409

    designer = await client.post('/api/v1/bots/catalog/frontend_designer/install')
    assert designer.status_code == 201, designer.text
    assert designer.json()['handle'] == 'frontend_designer'
    assert 'Frontend Designer for OpenBot' in designer.json()['instructions']
    assert (await client.post('/api/v1/bots/catalog/no-such/install')).status_code == 404


def test_catalog_entry_exposes_repository_instruction_setting():
    from openbot.bots.catalog import CATALOG_BY_ID

    engineer = next(entry for entry in CATALOG_BY_ID.values() if entry["handle"] == "engineer")
    assert engineer["load_repository_instructions"] is True


async def test_catalog_install_rejects_invalid_handle(client):
    response = await client.post(
        '/api/v1/bots/catalog/engineer/install',
        json={'handle': 'Invalid Handle!'},
    )
    assert response.status_code == 422
    bots = (await client.get('/api/v1/bots')).json()
    assert all(bot['handle'] != 'Invalid Handle!' for bot in bots)


async def test_catalog_install_preserves_existing_bot(client):
    existing = await client.post('/api/v1/bots', json={
        'handle': 'custom', 'name': 'Custom', 'instructions': 'Keep me',
    })
    assert existing.status_code == 201
    installed = await client.post('/api/v1/bots/catalog/engineer/install')
    assert installed.status_code == 201
    bots = (await client.get('/api/v1/bots')).json()
    assert next(bot for bot in bots if bot['handle'] == 'custom')['instructions'] == 'Keep me'
