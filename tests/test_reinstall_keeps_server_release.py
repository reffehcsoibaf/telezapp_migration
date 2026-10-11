"""A library-only reinstall must not roll the WPPConnect Server back.

The startup gate offers a reinstall when the server is below the homologated
minimum (the homologated tag is right) or when only the library drifted from
api/package.json (the server is fine). The second case used to install the
homologated tag as well, so a server updated past it (e.g. 2.10.42 vs a
homologated 2.10.27) was downgraded, and the update checker then offered the
same update again.
"""

from pathlib import Path

from core.wpp_runtime import reinstall_tag_for_library_repair

HOMOLOGATED = "v2.10.27"


def test_a_newer_server_is_kept():
    assert reinstall_tag_for_library_repair("2.10.42", HOMOLOGATED) == "v2.10.42"


def test_the_same_release_is_kept():
    assert reinstall_tag_for_library_repair("2.10.27", HOMOLOGATED) == "v2.10.27"


def test_a_leading_v_is_accepted():
    assert reinstall_tag_for_library_repair("v2.10.42", HOMOLOGATED) == "v2.10.42"


def test_numeric_order_not_text_order():
    assert reinstall_tag_for_library_repair("2.10.100", "v2.10.27") == "v2.10.100"
    assert reinstall_tag_for_library_repair("2.9.99", "v2.10.27") == "v2.10.27"


def test_an_older_server_gets_the_homologated_tag():
    assert reinstall_tag_for_library_repair("2.10.18", HOMOLOGATED) == HOMOLOGATED


def test_an_unreadable_installed_version_falls_back_to_the_homologated_tag():
    for bad in ("", None, "banana", "2.10.42-beta.1", "2"):
        assert reinstall_tag_for_library_repair(bad, HOMOLOGATED) == HOMOLOGATED, bad


def test_with_no_homologated_tag_the_installed_release_is_still_kept():
    assert reinstall_tag_for_library_repair("2.10.42", "") == "v2.10.42"


def test_with_nothing_known_it_returns_empty_so_the_latest_release_is_resolved():
    assert reinstall_tag_for_library_repair("", "") == ""


def test_the_gate_uses_it_only_for_the_library_branch():
    source = (Path(__file__).resolve().parent.parent / "client" / "main.py").read_text(encoding="utf-8")
    start = source.index("reinstall_tag_for_library_repair(")
    block = source[source.rindex("if not outdated:", 0, start):start + 200]
    assert "if not outdated:" in block
    # The server-too-old branch keeps the homologated tag untouched.
    assert source.index("minimum_tag = homologated_wpp_tag(") < start < source.index("forced_tag=minimum_tag")
