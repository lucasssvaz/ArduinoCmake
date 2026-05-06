from pathlib import Path

from acmake.cmakegen import _argv_set_depfile_mf, _emit_depfile


def test_argv_set_depfile_mf(tmp_path: Path) -> None:
    dep = tmp_path / "x" / "out.d"
    dep.parent.mkdir(parents=True)
    argv = ["g++", "-MMD", "-MF", "/wrong/path.d", "-c", "a.cpp"]
    out = _argv_set_depfile_mf(argv, dep)
    assert out[3] == str(dep.resolve())


def test_argv_set_depfile_mf_relative_to_build_dir(tmp_path: Path) -> None:
    bd = tmp_path / "build"
    bd.mkdir()
    dep = bd / ".acmake_deps" / "src__Foo.cpp.o.d"
    dep.parent.mkdir(parents=True)
    argv = ["g++", "-MMD", "-MF", "/wrong/path.d", "-c", "a.cpp"]
    out = _argv_set_depfile_mf(argv, dep, mf_relative_to=bd)
    assert out[3] == ".acmake_deps/src__Foo.cpp.o.d"


def test_depfile_only_when_mf_matches(tmp_path: Path) -> None:
    dep = tmp_path / "out.o.d"
    assert not _emit_depfile(dep, ["g++", "-c", "a.cpp"])
    assert not _emit_depfile(dep, ["g++", "-MMD", "-c", "a.cpp"])
    assert _emit_depfile(
        dep,
        ["g++", "-MMD", "-MF", str(dep), "-c", "a.cpp", "-o", str(tmp_path / "out.o")],
    )
