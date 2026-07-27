def test_latest_stable_ignores_drafts_and_prereleases():
    from lite_app.updates import select_latest_stable

    result = select_latest_stable(
        [
            {"tag_name": "v1.2.0-beta.1", "prerelease": True, "draft": False},
            {"tag_name": "v1.1.0", "prerelease": False, "draft": True},
            {
                "tag_name": "v1.0.2",
                "prerelease": False,
                "draft": False,
                "html_url": "https://github.com/liumingyang-maker/daily-record-ocr-lite/releases/tag/v1.0.2",
            },
            {
                "tag_name": "v1.0.1",
                "prerelease": False,
                "draft": False,
                "html_url": "https://github.com/liumingyang-maker/daily-record-ocr-lite/releases/tag/v1.0.1",
            },
        ]
    )

    assert result == {
        "version": "1.0.2",
        "tag": "v1.0.2",
        "url": "https://github.com/liumingyang-maker/daily-record-ocr-lite/releases/tag/v1.0.2",
    }


def test_update_result_uses_installer_for_desktop_and_git_for_source():
    from lite_app.updates import build_update_result

    latest = {"version": "1.0.2", "tag": "v1.0.2", "url": "https://example.test/release"}

    desktop = build_update_result("1.0.1", latest, install_kind="desktop")
    source = build_update_result("1.0.1", latest, install_kind="source")

    assert desktop["update_available"] is True
    assert desktop["update_method"] == "installer"
    assert source["update_method"] == "git"


def test_update_check_failure_is_safe_and_contains_no_exception_details():
    from lite_app.updates import check_for_stable_update

    def failing_fetcher():
        raise RuntimeError("Authorization: secret-value")

    result = check_for_stable_update("1.0.1", fetcher=failing_fetcher)

    assert result["status"] == "UNAVAILABLE"
    assert result["error_category"] == "UPDATE_CHECK_FAILED"
    assert "secret-value" not in repr(result)


def test_desktop_install_never_recommends_git_update():
    from lite_app.updates import update_instructions

    assert "Git" not in update_instructions("desktop", platform_name="win32")
    assert "安装包" in update_instructions("desktop", platform_name="win32")
    assert "Git" in update_instructions("source", platform_name="win32")
