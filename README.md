# Systems Engineering Assistant

This is the implementation repository for my research on how systems
engineering can be democratized, specifically how MBSE can improve product
development for small/mid-size organizations and resource-constrained teams.

See the SE task map here: ... *(link TBD)*
Master's thesis: ... *(link TBD)*

firslty i will, show you how to start sysmlv2 modeling with and open source toolkit. 

1) clone the sysml release repo and install jupyter lab
2) open it here with the command ...
3) run all cells and play around 
usefull sysml tutorials
- advent 
- 
clone the implementation reposiotory


- install this vs code extansion for syntax highliting and ...
- next install the parser to enable your Code AI assistant to validate the syntax

Alternativly you migt use other commecial or open source toolts
https://github.com/elan8/spec42

https://github.com/DAF-Digital-Transformation-Office/PySysML2
[@liuMAS4SysMLMultiAgentFramework2026]

- system modleing
- sysside
- her elist of sysml complient tools


## Repository structure
- **`examples/`** — SysML v2 models illustrating the profiles defined in the
  SE task map.
- **`tools/`** — small standalone utilities that support the research but
  don't (yet) warrant their own repo or PyPI package (e.g. the Mermaid→DOT
  converter).
- **`Lit_review_AI_for_SE/`** — reproductions of prior published work. Each
  subfolder corresponds to one paper/approach; see `SysTemp/README.md` for
  the first one.

Each folder has its own README with more detail; this top-level one covers
environment setup and the shared SysML v2 validation tooling.

## Installation

### Create a virtual environment (Windows)

```cmd
python -m venv venv
venv\Scripts\activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Set your OpenAI API key

```bash
# macOS/Linux
export OPENAI_API_KEY=sk-...
```

```cmd
:: Windows cmd
set OPENAI_API_KEY=sk-...
```

**Never commit a real key to this file or any other tracked file** — treat
`OPENAI_API_KEY` as a secret, keep it in your shell environment or an
untracked `.env` file only.

## Deterministic SysML v2 parser (OMG Pilot Implementation)

`Lit_review_AI_for_SE/SysTemp/parser.py` (`ParserAgent`) shells out to a
local jar at `./parser.jar` for ground-truth syntax/semantic validation.
That jar is not part of this repo — it has to be built from the official OMG
reference implementation:
https://github.com/Systems-Modeling/SysML-v2-Pilot-Implementation

### Prerequisites

- A **JDK** 21 — not just a JRE. `JAVA_HOME` must point at an install that
  has `javac`; a JRE-only install (like a bare `jre-21...` folder) will fail
  the compile step with:
  `No compiler is provided in this environment. Perhaps you are running on
  a JRE rather than a JDK?`
  Check before building:
  ```powershell
  Test-Path "$env:JAVA_HOME\bin\javac.exe"   # must print True
  & "$env:JAVA_HOME\bin\java.exe" -version   # must report 21.x
  ```
  If you don't have a JDK 21 yet, install one, e.g. Eclipse Temurin 21 LTS:
  https://adoptium.net/temurin/releases/?version=21 (or any other JDK 21
  distribution — Semeru, Microsoft Build of OpenJDK, Oracle, etc., as long
  as it's a full JDK). Building with a newer major version (e.g. a JDK 26
  you may already have installed) is not recommended here — this project's
  `pom.xml` pins the Tycho execution environment to `JavaSE-21`, and a
  mismatched compiler can produce other, harder-to-diagnose build errors.
- Internet access (the build pulls dependencies from Maven Central plus the
  Eclipse 2025-12 / Xtext / QVTo p2 update sites — it will fail offline).
- A git clone of the pilot implementation repo, e.g.
  `C:\sources\SysML-v2-Pilot-Implementation`.

set JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-21.0.11.10-hotspot


### Build

From the root of the cloned `SysML-v2-Pilot-Implementation` repo:

Find where a JDK 21 (not JRE) is installed if you don't already know. List
what's under the usual install roots and check each for `javac.exe`:

```powershell
Get-ChildItem "C:\Program Files\Java", "C:\Program Files\Eclipse Adoptium", "C:\Program Files\Semeru" -ErrorAction SilentlyContinue -Directory |
  ForEach-Object {
    [pscustomobject]@{
      Path      = $_.FullName
      HasJavac  = Test-Path (Join-Path $_.FullName 'bin\javac.exe')
    }
  }
```

Pick one where `HasJavac` is `True`, then:

```cmd
set JAVA_HOME=C:\path\to\jdk-21
mvnw.cmd clean install
```

This is a full Eclipse Tycho multi-module reactor build (Xtext-generated
KerML/SysML parsers, validators, the interactive engine, Jupyter kernel,
editor plugins, etc.). Expect it to take a while on first run and to need a
few GB of downloaded dependencies. `mvn clean install` (system Maven instead
of the wrapper) does the same thing.

The relevant output ends up at:

```
org.omg.sysml.interactive/target/org.omg.sysml.interactive-<version>-all.jar
```

(currently `org.omg.sysml.interactive-0.60.1-SNAPSHOT-all.jar`), an
executable jar with main class `org.omg.sysml.interactive.SysMLInteractive`.
This is the deterministic parser/validator — it runs the real generated
Xtext grammar plus the OMG semantic validator, no LLM involved.

### Confirming the build/install worked

1. **Check the jar exists:**

   ```powershell
   Get-ChildItem org.omg.sysml.interactive\target\*-all.jar
   ```

   If this returns nothing, the `org.omg.sysml.interactive` module didn't
   build — scroll up through the `mvnw.cmd` output for the first `ERROR` /
   `BUILD FAILURE`, since Tycho reactor builds stop at the first failing
   module and everything after it is simply skipped.

2. **Confirm it launches:**

   ```powershell
   echo %exit | java -jar org.omg.sysml.interactive\target\org.omg.sysml.interactive-0.60.1-SNAPSHOT-all.jar
   ```

   You should see a `SysML v2 Pilot Implementation` banner, a `0>` prompt,
   then a clean exit. If instead you get a `ClassNotFoundException` or
   `NoClassDefFoundError`, the `-all.jar` was built without its bundled
   dependencies (check the `package-jar` step in
   `org.omg.sysml.interactive/pom.xml` ran, not just `compile`).

3. **Smoke-test actual parsing** with one valid and one intentionally
   invalid snippet, and confirm the tool tells them apart:

   ```powershell
   @"
   %
   package Test { part def Foo; }
   %
   %exit
   "@ | java -jar org.omg.sysml.interactive\target\org.omg.sysml.interactive-0.60.1-SNAPSHOT-all.jar
   ```

   should complete with no errors reported, while

   ```powershell
   @"
   %
   package Test { part def Foo
   %
   %exit
   "@ | java -jar org.omg.sysml.interactive\target\org.omg.sysml.interactive-0.60.1-SNAPSHOT-all.jar
   ```

   (missing closing brace) should print a syntax error pointing at the
   missing `}`. If both snippets come back clean, something's wrong with the
   install even though the jar runs — the grammar/validator isn't actually
   being invoked.

Only once step 3 distinguishes valid from invalid input should you consider
the parser correctly installed and move on to wiring it into `parser.py`
below.

### Using it to validate a `.sysml` file

The jar's `main()` starts an interactive REPL reading from stdin rather than
taking a file path as an argument. To validate a whole file
non-interactively, wrap its contents in a `%`/`%` multi-line block and pipe
it in, e.g. from PowerShell:

```powershell
$body = Get-Content -Raw path\to\file.sysml
@"
%
$body
%
%exit
"@ | java -jar org.omg.sysml.interactive\target\org.omg.sysml.interactive-0.60.1-SNAPSHOT-all.jar
```

Output lists syntax errors first (if any), otherwise semantic
errors/warnings from the validator, otherwise the parsed root element — this
is what `ParserAgent._validate_with_java_parser` expects on stdout/stderr.

### Wiring it into this repo

Once built, either:

- copy the `-all.jar` into `Lit_review_AI_for_SE/SysTemp/parser.jar`, or
- point `ParserAgent(java_parser_path=...)` at the built jar's absolute path.

Note the current `ParserAgent._validate_with_java_parser` invokes
`java -jar <jar> <temp_file>` with the file path as a CLI arg, which does
**not** match the REPL-based `main()` above (`args[0]` there is treated as a
remote-project name to load via the SysML v2 API, not a local file to
parse). To use the built jar as-is with the existing `parser.py`, either:

- adjust `_validate_with_java_parser` to pipe the `%`/`%`-wrapped file
  contents via stdin as shown above, or
- add a small wrapper `main` in a new class that calls
  `SysMLInteractive.process(Files.readString(path))` directly and prints
  the result.
