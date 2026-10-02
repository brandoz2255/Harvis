"""web_read must not pass a sign-in page off as the page the user asked about."""

from agent_reach.tools import _login_walled


def test_instagram_sign_in_page_is_a_wall():
    text = "Instagram\n\nLog in · Sign up\nSee photos and videos from friends."
    assert _login_walled("https://www.instagram.com/nasa/", text)


def test_subdomain_and_other_meta_hosts_count():
    assert _login_walled("https://m.facebook.com/nasa", "Log in to Facebook")
    assert _login_walled("https://www.threads.net/@nasa", "Log in with Instagram")


def test_ordinary_site_mentioning_login_is_not_a_wall():
    assert not _login_walled("https://example.com/post", "Log in to comment below.")


def test_walled_host_with_real_content_passes():
    assert not _login_walled("https://www.instagram.com/p/abc/", "NASA: a new image of Jupiter's moon Io.")
