"""Type-check the Unity scripts without opening the editor.

The editor holds the project open while it is being played, so a batch-mode
compile refuses to start ("another Unity instance is running"), and for most of
this project's life that meant every C# change shipped unverified - reviewed by
eye and hoped for. Two of the rounds in `docs/hand-tracking-report.md` end with
"could not be compiled here", and one of those was a 26 %-to-target rotation
bug that took a session to find.

A compile does not need the editor. It needs the same references the editor
would use: the engine assemblies that ship with the installed version, plus
whatever the project last compiled into `Library/ScriptAssemblies`. Feed those
to the .NET SDK's Roslyn and a syntax or type error comes back in about two
seconds, with the file and line.

    uv run --locked python tools/check_unity_scripts.py
    uv run --locked python tools/check_unity_scripts.py --unity "D:/Unity/6000.3.27f1"

Exit code 0 means the scripts type-check; 1 means they do not, and the compiler
output is printed as-is. Nothing is written to the project: the scratch project
lives under `.scratch/`, which is ignored.

Caveat: this checks types, not behaviour. It cannot tell you the avatar's wrist
is 180 degrees out - only that the code that turns it compiles.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UNITY_PROJECT = REPO_ROOT / "unity"
SCRIPT_ASSEMBLIES = UNITY_PROJECT / "Library" / "ScriptAssemblies"
SOURCES = [
    "Assets/AstraUnity/Runtime",
    "Packages/com.dollfight.humanoid/Runtime",
]
# Suppressed on purpose: CS0436 is "this type is also in a referenced assembly,
# the source wins", which is exactly what happens when the folder is compiled
# again while the project's own DLLs are referenced for everything else.
SUPPRESSED = "CS0436,CS0618,CS0649,CS0169,CS0414"


def project_version() -> str:
    text = (UNITY_PROJECT / "ProjectSettings" / "ProjectVersion.txt").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("m_EditorVersion:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("unity/ProjectVersion.txt 里没有 m_EditorVersion")


def find_editor(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("UNITY_EDITOR"):
        candidates.append(Path(os.environ["UNITY_EDITOR"]))
    version = project_version()
    candidates += [
        Path("H:/Unity") / version,
        Path("D:/Unity") / version,
        Path("C:/Program Files/Unity/Hub/Editor") / version,
    ]
    for candidate in candidates:
        if (candidate / "Editor/Data/Managed/UnityEngine").is_dir():
            return candidate
    raise SystemExit(
        f"找不到 Unity 编辑器。传 --unity <安装目录>，或设 UNITY_EDITOR。\n工程要求 {version}。"
    )


def write_project(target: Path, editor: Path) -> int:
    references = sorted((editor / "Editor/Data/Managed/UnityEngine").glob("*.dll"))
    references += sorted(SCRIPT_ASSEMBLIES.glob("*.dll")) if SCRIPT_ASSEMBLIES.is_dir() else []
    if not references:
        raise SystemExit("没有可引用的程序集：先让 Unity 打开一次工程，生成 ScriptAssemblies")
    includes = "\n".join(
        f'    <Compile Include="{UNITY_PROJECT / source / "*.cs"}" />' for source in SOURCES
    )
    refs = "\n".join(f'    <Reference Include="{dll}" />' for dll in references)
    (target / "CheckUnity.csproj").write_text(
        f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.1</TargetFramework>
    <AssemblyName>CheckUnity</AssemblyName>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <LangVersion>9.0</LangVersion>
    <Nullable>disable</Nullable>
    <NoWarn>{SUPPRESSED}</NoWarn>
  </PropertyGroup>
  <ItemGroup>
{includes}
  </ItemGroup>
  <ItemGroup>
{refs}
  </ItemGroup>
</Project>
""",
        encoding="utf-8",
    )
    return len(references)


def main() -> int:
    parser = argparse.ArgumentParser(description="Type-check the Unity scripts offline")
    parser.add_argument("--unity", default=None, help="Unity editor install directory")
    parser.add_argument("--keep", action="store_true", help="keep the generated project")
    args = parser.parse_args()

    if shutil.which("dotnet") is None:
        print("没有装 .NET SDK（dotnet）。装一个，或在编辑器里编译。")
        return 2
    editor = find_editor(args.unity)
    target = Path(tempfile.mkdtemp(prefix="dollfight-check-"))
    try:
        count = write_project(target, editor)
        print(f"用 {editor.name} 的 {count} 个程序集编译 {len(SOURCES)} 个脚本目录…")
        build = subprocess.run(
            ["dotnet", "build", "-v", "q", "--nologo"],
            cwd=target,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = (build.stdout or "") + (build.stderr or "")
        errors = [line for line in output.splitlines() if ": error " in line]
        if build.returncode == 0:
            print("编译通过，0 个错误。")
            return 0
        print("\n".join(errors) if errors else output[-4000:])
        print(f"\n编译失败：{len(errors)} 个错误。")
        return 1
    finally:
        if args.keep:
            print(f"生成的工程保留在 {target}")
        else:
            shutil.rmtree(target, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
