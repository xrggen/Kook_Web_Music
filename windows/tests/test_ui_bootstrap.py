from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WINDOWS_TEMPLATES = ROOT / "windows" / "templates"
EDGE_TEMPLATES = ROOT / "edge" / "templates"
APP_PAGES = (
    WINDOWS_TEMPLATES / "dashboard.html",
    WINDOWS_TEMPLATES / "library.html",
    WINDOWS_TEMPLATES / "account.html",
    WINDOWS_TEMPLATES / "status.html",
    WINDOWS_TEMPLATES / "settings.html",
    WINDOWS_TEMPLATES / "users.html",
    EDGE_TEMPLATES / "settings.html",
)


def test_ui_preferences_bootstrap_is_loaded_from_every_app_page_head():
    for template in APP_PAGES:
        markup = template.read_text(encoding="utf-8")
        include_at = markup.index("{% include '_app_early_ui.html' %}")
        assert include_at < markup.index("</head>")
        assert "filename='js/app-ui.js'" not in markup


def test_early_ui_loads_theme_before_prepaint_preferences():
    markup = (WINDOWS_TEMPLATES / "_app_early_ui.html").read_text(encoding="utf-8")
    theme_at = markup.index("filename='css/theme.css'")
    mobile_at = markup.index("filename='css/mobile.css'")
    polish_at = markup.index("filename='css/mobile-polish.css'")
    auth_at = markup.index("filename='css/auth.css'")
    theme_init_at = markup.index("filename='js/theme-init.js'")
    auth_client_at = markup.index("filename='js/auth-client.js'")
    bootstrap_at = markup.index("filename='js/app-ui.js'")
    assert theme_at < mobile_at < polish_at < auth_at
    assert auth_at < theme_init_at < auth_client_at < bootstrap_at
    assert 'id="kook-theme-stylesheet"' in markup
    assert 'id="kook-mobile-stylesheet"' in markup
    assert 'id="kook-mobile-polish-stylesheet"' in markup


def test_sidebar_does_not_load_layout_resources_after_body_rendering_starts():
    sidebar = (WINDOWS_TEMPLATES / "_app_sidebar.html").read_text(encoding="utf-8")
    assert "theme-init.js" not in sidebar
    assert "mobile.css" not in sidebar
    assert "auth.css" not in sidebar
    assert "auth-client.js" not in sidebar


def test_users_page_receives_sidebar_health_refresh_script():
    users = (WINDOWS_TEMPLATES / "users.html").read_text(encoding="utf-8")
    app_ui = (WINDOWS_TEMPLATES / "_app_early_ui.html").read_text(encoding="utf-8")
    assert "sidebar-health-dot" in (WINDOWS_TEMPLATES / "_app_sidebar.html").read_text(encoding="utf-8")
    assert "{% include '_app_early_ui.html' %}" in users
    assert "filename='js/app-ui.js'" in app_ui
