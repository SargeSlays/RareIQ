from tools import package_desktop_runtime as package


def test_runtime_source_allowlist_excludes_operator_files_and_build_artifacts():
    for path in ['app.py', 'rareiq/web/server.py', 'rareiq/core/runtime_paths.py',
                 'rareiq/web/static/control.html', 'tools/desktop_backend.py']:
        assert package.approved_source(path)
    for path in ['obs_settings.json', 'storage_config.json', 'rareiq_secrets.json',
                 'captures/person.jpg', 'rareiq/data/temporal_multi_card_history.json',
                 'rareiq/web/static/../secret.json', '../app.py', '.venv/private.py',
                 'tools/qa_native_desktop_fixture.py', 'desktop/tests/anything.cjs']:
        assert not package.approved_source(path)
    for path in [r'rareiq/web/static/..\..\..\..\outside.txt',
                 r'C:\rareiq\web\static\outside.txt', 'C:app.py']:
        assert not package.approved_source(path)


def test_embedded_runtime_is_pinned_to_a_verified_archive():
    assert package.PYTHON_URL.startswith('https://www.python.org/ftp/python/')
    assert len(package.PYTHON_SHA256) == 64
