from mcp_vertica.server import SAFE_NAME, jinja


def test_template_name_guard():
    assert SAFE_NAME.match("get_version.sql")
    assert not SAFE_NAME.match("../../etc/passwd")


def test_render_contains_select():
    template = jinja.get_template("get_version.sql")
    sql = template.render()
    assert "SELECT" in sql.upper()
