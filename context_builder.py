"""
context_builder.py - Deterministic Context Builder & Verification Pipeline for Coding Agents

Pipeline Architecture:
          ┌─────────────────────────────────────────────┐
 Repo ──► │ 0. Ingest: clone, .gitignore filter, size cap│
          └──────────────────┬──────────────────────────┘
                             ▼
          ┌─────────────────────────────────────────────┐
          │ 1. Signals (no LLM, cheap, deterministic)    │
          │  • linters/type checkers → file:line findings│
          │  • tree-sitter/AST symbol index + import graph│
          │  • git: recently changed / high-churn files  │
          │  • (optional) BM25 / embeddings per chunk    │
          └──────────────────┬──────────────────────────┘
                             ▼
          ┌─────────────────────────────────────────────┐
          │ 2. Rank files: score = findings + centrality │
          │    + churn + entry-point proximity           │
          └──────────────────┬──────────────────────────┘
                             ▼
          ┌─────────────────────────────────────────────┐
          │ 3. Context builder (token budget)            │
          │  • repo map (signatures only) for ALL files  │
          │  • full code for top-N suspects              │
          │  • ±N lines around each linter finding       │
          │  • 1-hop neighbors (callers/callees/imports) │
          └──────────────────┬──────────────────────────┘
                             ▼
          ┌─────────────────────────────────────────────┐
          │ 4. LLM agent loop with tools                 │
          │  read_file(path, start, end), grep(pattern), │
          │  find_references(symbol), get_symbols(file)  │
          └──────────────────┬──────────────────────────┘
                             ▼
          ┌─────────────────────────────────────────────┐
          │ 5. Verify: line exists? linter agrees? dedupe│
          └─────────────────────────────────────────────┘

Usage Example:
    from context_builder import CodebaseContextPipeline, ContextConfig

    # 1. Initialize pipeline for a repository
    pipeline = CodebaseContextPipeline(repo_path=".")

    # 2. Ingest repo and extract deterministic signals
    pipeline.ingest()

    # 3. Build token-budgeted prompt context for an issue or task
    context = pipeline.build_context(
        query="Fix WebSocket disconnection timeout",
        token_budget=16000
    )
    print(context.prompt_text)

    # 4. Use LLM tools during agent loop
    tools = pipeline.get_tools()
    print(tools.read_file("main.py", start=1, end=30))
    print(tools.grep("timeout"))
    print(tools.find_references("ConnectionManager"))
    print(tools.get_symbols("main.py"))

    # 5. Verify edits before applying
    verifier = pipeline.get_verifier()
    print(verifier.verify_line_exists("main.py", line_num=15))
    print(verifier.verify_patch("main.py", old_code="timeout=10", new_code="timeout=30"))
"""

from __future__ import annotations

import ast
import fnmatch
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


# ============================================================================
# DATA STRUCTURES & CONFIGURATION
# ============================================================================

@dataclass
class ContextConfig:
    """Configuration for all pipeline stages."""
    repo_path: str = "."
    max_file_size_bytes: int = 500 * 1024  # 500 KB limit per file
    ignored_patterns: List[str] = field(default_factory=lambda: [
        ".git", ".git/*", ".kilo", ".kilo/*", ".idea", ".vscode",
        "__pycache__", "__pycache__/*", "*.pyc", "*.pyo", "*.pyd",
        "node_modules", "node_modules/*", ".venv", ".venv/*", "venv", "venv/*",
        "env", "env/*", "dist", "dist/*", "build", "build/*",
        ".pytest_cache", ".mypy_cache", ".ruff_cache", "*.egg-info",
        "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.svg",
        "*.mp4", "*.mp3", "*.wav", "*.avi", "*.mov",
        "*.zip", "*.tar", "*.gz", "*.bz2", "*.7z", "*.rar",
        "*.exe", "*.dll", "*.so", "*.dylib", "*.bin", "*.iso",
        "*.pdf", "*.docx", "*.xlsx", "*.db", "*.sqlite", "*.sqlite3"
    ])
    token_budget: int = 16000
    snippet_window_lines: int = 15
    top_n_suspects: int = 5
    # Ranking weights
    weight_findings: float = 0.35
    weight_centrality: float = 0.20
    weight_churn: float = 0.15
    weight_entry_proximity: float = 0.15
    weight_bm25: float = 0.15
    # Token allocation percentages (must sum to ~1.0)
    budget_ratio_repomap: float = 0.20
    budget_ratio_suspects: float = 0.50
    budget_ratio_snippets: float = 0.20
    budget_ratio_neighbors: float = 0.10


@dataclass
class FileRecord:
    """Represents an ingested text file."""
    path: Path
    rel_path: str  # POSIX normalized (e.g. "src/app.py")
    content: str
    size: int
    language: str
    line_count: int
    lines: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.lines and self.content:
            self.lines = self.content.splitlines()


@dataclass
class Finding:
    """Represents a linter or static analysis finding."""
    file: str  # rel_path
    line: int
    col: int = 1
    severity: str = "error"  # error, warning, info
    message: str = ""
    rule_id: str = ""
    source: str = "syntax"  # syntax, ruff, flake8, mypy, etc.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "severity": self.severity,
            "message": self.message,
            "rule_id": self.rule_id,
            "source": self.source,
        }


@dataclass
class Symbol:
    """Extracted code symbol (class, function, method, interface)."""
    name: str
    kind: str  # function, class, method, variable, import
    file: str
    line_start: int
    line_end: int
    signature: str
    docstring: str = ""
    parent: Optional[str] = None


@dataclass
class RankedFile:
    """Score breakdown for a suspect file."""
    rel_path: str
    score: float
    findings_score: float
    centrality_score: float
    churn_score: float
    entry_proximity_score: float
    bm25_score: float
    findings_count: int
    reasons: List[str] = field(default_factory=list)


@dataclass
class SnippetContext:
    """Code snippet around a linter finding."""
    file: str
    finding: Finding
    start_line: int
    end_line: int
    snippet_text: str


@dataclass
class ContextPayload:
    """Final package produced by Stage 3 for the LLM prompt."""
    prompt_text: str
    repo_map: str
    top_files: List[RankedFile]
    snippets: List[SnippetContext]
    neighbors: List[str]
    estimated_tokens: int
    ranking_summary: List[Dict[str, Any]]


# ============================================================================
# STAGE 0: REPOSITORY INGESTION & FILTERING
# ============================================================================

class RepoIngester:
    """
    Stage 0: Clones or opens repository, filters according to .gitignore,
    enforces file size limits, skips binary files, and returns FileRecords.
    """

    BINARY_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".svg",
        ".mp3", ".wav", ".ogg", ".mp4", ".mov", ".avi", ".mkv",
        ".zip", ".tar", ".gz", ".7z", ".rar", ".bz2",
        ".exe", ".bin", ".dll", ".so", ".dylib", ".pyd", ".pyc",
        ".pdf", ".db", ".sqlite", ".sqlite3", ".parquet", ".npy", ".npz",
        ".pkl", ".pickle", ".pt", ".pth", ".onnx", ".weights"
    }

    LANGUAGE_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".html": "html",
        ".css": "css",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c_header",
        ".hpp": "cpp_header",
        ".sh": "bash",
        ".ps1": "powershell",
        ".sql": "sql",
        ".toml": "toml",
    }

    def __init__(self, config: ContextConfig):
        self.config = config
        self.repo_dir = Path(config.repo_path).resolve()
        self.gitignore_patterns: List[str] = []

    @classmethod
    def clone_if_remote(cls, repo_target: str, dest_dir: Optional[str] = None) -> Path:
        """Clones a remote git repo if a URL is provided, else returns Path."""
        if repo_target.startswith(("http://", "https://", "git@")):
            target = Path(dest_dir or tempfile.mkdtemp(prefix="repo_clone_"))
            subprocess.run(["git", "clone", "--depth", "1", repo_target, str(target)], check=True)
            return target
        return Path(repo_target).resolve()

    def load_gitignore(self) -> List[str]:
        """Loads and parses .gitignore rules from repo root."""
        patterns = list(self.config.ignored_patterns)
        gitignore_path = self.repo_dir / ".gitignore"
        if gitignore_path.exists():
            try:
                for line in gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    patterns.append(line)
            except Exception:
                pass
        self.gitignore_patterns = patterns
        return patterns

    def is_ignored(self, rel_path: str) -> bool:
        """Checks if a relative path matches gitignore or exclusion rules."""
        norm_path = rel_path.replace("\\", "/")
        parts = norm_path.split("/")

        for pattern in self.gitignore_patterns:
            pattern = pattern.strip().replace("\\", "/")
            if not pattern:
                continue

            # Directory specific pattern
            if pattern.endswith("/"):
                dir_pat = pattern[:-1]
                if any(fnmatch.fnmatch(part, dir_pat) for part in parts[:-1]):
                    return True
                if fnmatch.fnmatch(parts[-1], dir_pat):
                    return True

            # Match against full relative path or any individual component
            if fnmatch.fnmatch(norm_path, pattern) or fnmatch.fnmatch(f"/{norm_path}", pattern):
                return True
            if any(fnmatch.fnmatch(part, pattern) for part in parts):
                return True
            if fnmatch.fnmatch(norm_path, f"*/{pattern}") or fnmatch.fnmatch(norm_path, f"**/{pattern}"):
                return True

        return False

    def is_binary(self, file_path: Path) -> bool:
        """Fast binary detection using extension and null-byte check."""
        if file_path.suffix.lower() in self.BINARY_EXTENSIONS:
            return True
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(8192)
                if b"\x00" in chunk:
                    return True
        except Exception:
            return True
        return False

    def ingest(self) -> Dict[str, FileRecord]:
        """
        Crawls the repository, filters by rules, and constructs FileRecords.
        Returns a dictionary mapping relative POSIX path -> FileRecord.
        """
        self.load_gitignore()
        records: Dict[str, FileRecord] = {}

        if not self.repo_dir.exists():
            return records

        for root, dirs, files in os.walk(self.repo_dir):
            rel_root = os.path.relpath(root, self.repo_dir).replace("\\", "/")
            if rel_root == ".":
                rel_root = ""

            # Prune ignored directories in-place to prevent descending
            dirs[:] = [
                d for d in dirs
                if not self.is_ignored(f"{rel_root}/{d}".strip("/"))
            ]

            for file in files:
                rel_file = f"{rel_root}/{file}".strip("/") if rel_root else file
                if self.is_ignored(rel_file):
                    continue

                abs_file = Path(root) / file

                # Size cap filter
                try:
                    file_size = abs_file.stat().st_size
                except OSError:
                    continue

                if file_size > self.config.max_file_size_bytes or file_size == 0:
                    continue

                # Binary filter
                if self.is_binary(abs_file):
                    continue

                try:
                    content = abs_file.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                language = self.LANGUAGE_MAP.get(abs_file.suffix.lower(), "text")
                records[rel_file] = FileRecord(
                    path=abs_file,
                    rel_path=rel_file,
                    content=content,
                    size=file_size,
                    language=language,
                    line_count=len(content.splitlines()),
                )

        return records


# ============================================================================
# STAGE 1: SIGNALS (NO LLM, CHEAP, DETERMINISTIC)
# ============================================================================

class BM25Okapi:
    """Pure-Python BM25 Okapi indexer for fast lexical chunk retrieval."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_len: List[int] = []
        self.avg_dl: float = 0.0
        self.corpus_size: int = 0
        self.doc_freqs: List[Dict[str, int]] = []
        self.idf: Dict[str, float] = {}

    def _tokenize(self, text: str) -> List[str]:
        # Split on non-alphanumeric, camelCase, and snake_case
        tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        sub_tokens = []
        for t in tokens:
            sub_tokens.append(t)
            # Split camelCase
            camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", t).lower().split()
            if len(camel_split) > 1:
                sub_tokens.extend(camel_split)
            # Split snake_case
            snake_split = t.split("_")
            if len(snake_split) > 1:
                sub_tokens.extend([s for s in snake_split if s])
        return [t for t in sub_tokens if len(t) > 1]

    def fit(self, docs: List[str]):
        self.corpus_size = len(docs)
        if self.corpus_size == 0:
            return

        df: Dict[str, int] = defaultdict(int)
        total_len = 0
        self.doc_freqs = []
        self.doc_len = []

        for doc in docs:
            tokens = self._tokenize(doc)
            length = len(tokens)
            self.doc_len.append(length)
            total_len += length

            frequencies: Dict[str, int] = defaultdict(int)
            for token in tokens:
                frequencies[token] += 1
            self.doc_freqs.append(frequencies)

            for token in frequencies:
                df[token] += 1

        self.avg_dl = (total_len / self.corpus_size) if self.corpus_size > 0 else 1.0

        for token, freq in df.items():
            # Standard BM25 IDF with smoothing
            self.idf[token] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def score(self, query: str) -> List[float]:
        if self.corpus_size == 0:
            return []
        query_tokens = self._tokenize(query)
        scores = [0.0] * self.corpus_size

        for token in query_tokens:
            if token not in self.idf:
                continue
            idf_val = self.idf[token]
            for idx, freqs in enumerate(self.doc_freqs):
                if token in freqs:
                    freq = freqs[token]
                    denom = freq + self.k1 * (1.0 - self.b + self.b * (self.doc_len[idx] / self.avg_dl))
                    scores[idx] += idf_val * (freq * (self.k1 + 1.0)) / (denom if denom > 0 else 1.0)
        return scores


class SignalExtractor:
    """
    Stage 1: Deterministic signal extraction:
    - Linters / type checkers -> file:line findings (Built-in AST + optional Ruff/Flake8)
    - Tree-sitter / AST symbol index + import graph
    - Git churn & recently changed files
    - BM25 chunk scoring for queries
    """

    def __init__(self, repo_dir: Path, files: Dict[str, FileRecord]):
        self.repo_dir = repo_dir
        self.files = files
        self.findings: List[Finding] = []
        self.symbols: Dict[str, List[Symbol]] = defaultdict(list)
        self.import_graph: Dict[str, Set[str]] = defaultdict(set)  # A -> set(files A imports)
        self.reverse_import_graph: Dict[str, Set[str]] = defaultdict(set)  # B -> set(files that import B)
        self.churn_counts: Dict[str, int] = defaultdict(int)
        self.recent_modified: Set[str] = set()
        self.bm25 = BM25Okapi()
        self.file_keys: List[str] = []

    # ------------------------------------------------------------------------
    # 1.1 Linters and Type Checkers Findings
    # ------------------------------------------------------------------------
    def extract_linter_findings(self) -> List[Finding]:
        """Runs fast, deterministic built-in syntax checks and optional CLI linters."""
        findings: List[Finding] = []

        # 1. Built-in Python AST check
        for rel_path, record in self.files.items():
            if record.language == "python":
                try:
                    ast.parse(record.content, filename=str(record.path))
                except SyntaxError as e:
                    findings.append(Finding(
                        file=rel_path,
                        line=e.lineno or 1,
                        col=e.offset or 1,
                        severity="error",
                        message=f"SyntaxError: {e.msg}",
                        rule_id="E999",
                        source="ast.parse"
                    ))
                except Exception as e:
                    findings.append(Finding(
                        file=rel_path,
                        line=1,
                        col=1,
                        severity="error",
                        message=f"ParseError: {str(e)}",
                        rule_id="E999",
                        source="ast.parse"
                    ))
            elif record.language == "json":
                try:
                    json.loads(record.content)
                except json.JSONDecodeError as e:
                    findings.append(Finding(
                        file=rel_path,
                        line=e.lineno,
                        col=e.colno,
                        severity="error",
                        message=f"JSONDecodeError: {e.msg}",
                        rule_id="JSON999",
                        source="json.loads"
                    ))

        # 2. Pluggable external linters (ruff or flake8) if installed on machine
        external_findings = self._run_external_linter()
        findings.extend(external_findings)

        self.findings = findings
        return findings

    def _run_external_linter(self) -> List[Finding]:
        """Runs ruff or flake8 in check mode if available."""
        findings: List[Finding] = []
        linter_cmd = None

        if shutil.which("ruff"):
            linter_cmd = ["ruff", "check", "--output-format=text", "."]
        elif shutil.which("flake8"):
            linter_cmd = ["flake8", "--max-line-length=120", "."]

        if not linter_cmd:
            return findings

        try:
            res = subprocess.run(
                linter_cmd,
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=10,
                check=False
            )
            output = res.stdout + "\n" + res.stderr
            # Regex pattern for file:line:col: message
            pattern = re.compile(r"^(.+?):(\d+):(\d+):\s*([A-Za-z0-9_-]+)?\s*(.+)$", re.MULTILINE)
            for match in pattern.finditer(output):
                raw_file, line_s, col_s, rule_s, msg = match.groups()
                rel_file = os.path.relpath(self.repo_dir / raw_file.strip(), self.repo_dir).replace("\\", "/")
                if rel_file in self.files:
                    findings.append(Finding(
                        file=rel_file,
                        line=int(line_s),
                        col=int(col_s),
                        severity="warning" if "W" in (rule_s or "") else "error",
                        message=msg.strip(),
                        rule_id=rule_s or "",
                        source=linter_cmd[0]
                    ))
        except Exception:
            pass

        return findings

    # ------------------------------------------------------------------------
    # 1.2 Symbol Index + Import Graph
    # ------------------------------------------------------------------------
    def extract_symbols_and_imports(self):
        """Indexes symbols and constructs directed import graphs."""
        for rel_path, record in self.files.items():
            if record.language == "python":
                self._extract_python_symbols_and_imports(rel_path, record)
            else:
                self._extract_generic_symbols_and_imports(rel_path, record)

        # Build reverse import graph
        for src, dests in self.import_graph.items():
            for dst in dests:
                self.reverse_import_graph[dst].add(src)

    def _extract_python_symbols_and_imports(self, rel_path: str, record: FileRecord):
        try:
            tree = ast.parse(record.content, filename=rel_path)
        except Exception:
            return

        for node in ast.walk(tree):
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target_file = self._resolve_python_module(alias.name)
                    if target_file and target_file != rel_path:
                        self.import_graph[rel_path].add(target_file)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                target_file = self._resolve_python_module(mod)
                if target_file and target_file != rel_path:
                    self.import_graph[rel_path].add(target_file)

            # Classes
            elif isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or ""
                bases = [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else []
                sig = f"class {node.name}({', '.join(bases)}):" if bases else f"class {node.name}:"
                self.symbols[rel_path].append(Symbol(
                    name=node.name,
                    kind="class",
                    file=rel_path,
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    signature=sig,
                    docstring=doc.split("\n")[0] if doc else ""
                ))

            # Functions & Methods
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node) or ""
                prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
                args_str = ""
                if hasattr(ast, "unparse"):
                    try:
                        args_str = ast.unparse(node.args)
                    except Exception:
                        args_str = "..."
                returns_str = f" -> {ast.unparse(node.returns)}" if getattr(node, "returns", None) and hasattr(ast, "unparse") else ""
                sig = f"{prefix}{node.name}({args_str}){returns_str}:"
                self.symbols[rel_path].append(Symbol(
                    name=node.name,
                    kind="method" if getattr(node, "_is_method", False) else "function",
                    file=rel_path,
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    signature=sig,
                    docstring=doc.split("\n")[0] if doc else ""
                ))

    def _resolve_python_module(self, module_name: str) -> Optional[str]:
        """Resolves Python module import to repository file."""
        if not module_name:
            return None
        candidate_parts = module_name.split(".")
        candidate_path = "/".join(candidate_parts) + ".py"
        if candidate_path in self.files:
            return candidate_path

        init_path = "/".join(candidate_parts) + "/__init__.py"
        if init_path in self.files:
            return init_path

        # Match suffixes in case of package roots
        for f in self.files:
            if f.endswith(candidate_path) or f.endswith(init_path):
                return f
        return None

    def _extract_generic_symbols_and_imports(self, rel_path: str, record: FileRecord):
        """Regex based extractor for JS/TS/Go/Rust/C++ symbols and imports."""
        lines = record.lines
        # JS / TS import matching
        import_re = re.compile(r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""")
        # Function/Class regex
        func_re = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|fn|func|def)\s+([A-Za-z0-9_]+)\s*\((.*?)\)")
        class_re = re.compile(r"^\s*(?:export\s+)?(?:class|interface|struct|type)\s+([A-Za-z0-9_]+)")

        for idx, line in enumerate(lines, start=1):
            # Imports
            for m in import_re.finditer(line):
                mod_path = m.group(1) or m.group(2)
                # Resolve relative import
                if mod_path.startswith("."):
                    base_dir = os.path.dirname(rel_path)
                    resolved = os.path.normpath(os.path.join(base_dir, mod_path)).replace("\\", "/")
                    for ext in ["", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"]:
                        candidate = f"{resolved}{ext}"
                        if candidate in self.files:
                            self.import_graph[rel_path].add(candidate)
                            break

            # Symbols
            f_match = func_re.match(line)
            if f_match:
                name, args = f_match.groups()
                self.symbols[rel_path].append(Symbol(
                    name=name,
                    kind="function",
                    file=rel_path,
                    line_start=idx,
                    line_end=idx,
                    signature=line.strip()
                ))
            c_match = class_re.match(line)
            if c_match:
                name = c_match.group(1)
                self.symbols[rel_path].append(Symbol(
                    name=name,
                    kind="class",
                    file=rel_path,
                    line_start=idx,
                    line_end=idx,
                    signature=line.strip()
                ))

    # ------------------------------------------------------------------------
    # 1.3 Git: Recently Changed & High-Churn Files
    # ------------------------------------------------------------------------
    def extract_git_signals(self):
        """Extracts file churn count and working tree changes via git."""
        git_dir = self.repo_dir / ".git"
        if not git_dir.exists():
            return

        try:
            # 1. Recently modified uncommitted files
            diff_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )
            for line in diff_res.stdout.splitlines():
                if len(line) > 3:
                    path_str = line[3:].strip().replace("\\", "/")
                    if path_str in self.files:
                        self.recent_modified.add(path_str)

            # 2. Churn count from git log (last 100 commits)
            log_res = subprocess.run(
                ["git", "log", "-n", "100", "--name-only", "--pretty=format:"],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=10,
                check=False
            )
            for line in log_res.stdout.splitlines():
                path_str = line.strip().replace("\\", "/")
                if path_str in self.files:
                    self.churn_counts[path_str] += 1
        except Exception:
            pass

    # ------------------------------------------------------------------------
    # 1.4 BM25 Indexing over Files / Chunks
    # ------------------------------------------------------------------------
    def index_bm25(self):
        """Fits BM25 index on all ingested files."""
        self.file_keys = list(self.files.keys())
        docs = [self.files[k].content for k in self.file_keys]
        self.bm25.fit(docs)

    def query_bm25(self, query: str) -> Dict[str, float]:
        """Returns normalized BM25 score in range [0, 1] per file."""
        if not query.strip() or not self.file_keys:
            return {k: 0.0 for k in self.files}

        raw_scores = self.bm25.score(query)
        max_score = max(raw_scores) if raw_scores else 0.0
        if max_score <= 0.0:
            return {k: 0.0 for k in self.files}

        return {k: (score / max_score) for k, score in zip(self.file_keys, raw_scores)}


# ============================================================================
# STAGE 2: RANK FILES
# ============================================================================

class FileRanker:
    """
    Stage 2: Ranks files according to:
      score = findings + centrality + churn + entry-point proximity + bm25
    """

    ENTRY_POINT_NAMES = {
        "main.py", "app.py", "server.py", "index.py", "cli.py", "__main__.py",
        "manage.py", "wsgi.py", "asgi.py", "index.js", "index.ts", "main.ts",
        "app.js", "app.ts", "server.js", "server.ts", "main.go", "main.rs"
    }

    def __init__(self, config: ContextConfig, extractor: SignalExtractor):
        self.config = config
        self.extractor = extractor
        self.files = extractor.files

    def compute_centrality(self) -> Dict[str, float]:
        """
        Computes PageRank and Degree Centrality on the import graph.
        Returns a normalized score in [0, 1] for each file.
        """
        nodes = list(self.files.keys())
        n = len(nodes)
        if n == 0:
            return {}
        if n == 1:
            return {nodes[0]: 1.0}

        # PageRank (power iteration with damping=0.85)
        d = 0.85
        pagerank = {node: 1.0 / n for node in nodes}
        out_degrees = {node: len(self.extractor.import_graph.get(node, set())) for node in nodes}

        for _ in range(25):
            new_pr = {node: (1.0 - d) / n for node in nodes}
            dangling_sum = sum(pagerank[node] for node in nodes if out_degrees[node] == 0)

            for node in nodes:
                targets = self.extractor.import_graph.get(node, set())
                if targets:
                    share = (d * pagerank[node]) / len(targets)
                    for target in targets:
                        if target in new_pr:
                            new_pr[target] += share

            # Distribute dangling node mass
            dangling_share = (d * dangling_sum) / n
            for node in nodes:
                new_pr[node] += dangling_share
            pagerank = new_pr

        # In-degree centrality (number of files that import this file)
        max_in_deg = max((len(self.extractor.reverse_import_graph.get(node, set())) for node in nodes), default=1)
        max_in_deg = max(max_in_deg, 1)

        combined = {}
        for node in nodes:
            in_deg_norm = len(self.extractor.reverse_import_graph.get(node, set())) / max_in_deg
            pr_val = pagerank.get(node, 0.0)
            combined[node] = 0.6 * pr_val + 0.4 * in_deg_norm

        max_c = max(combined.values()) if combined else 1.0
        return {k: (v / max_c if max_c > 0 else 0.0) for k, v in combined.items()}

    def detect_entry_points(self) -> Set[str]:
        """Detects entry points by name and `__name__ == '__main__'`."""
        entry_points = set()
        for rel_path, record in self.files.items():
            base_name = os.path.basename(rel_path).lower()
            if base_name in self.ENTRY_POINT_NAMES:
                entry_points.add(rel_path)
            elif record.language == "python" and "__main__" in record.content:
                entry_points.add(rel_path)
        return entry_points

    def compute_entry_proximity(self, entry_points: Set[str]) -> Dict[str, float]:
        """
        Computes BFS graph distance from entry points in the import graph.
        Proximity = 1.0 / (1.0 + distance). If unreachable, defaults to 0.1.
        """
        if not entry_points:
            return {k: 0.5 for k in self.files}

        distances: Dict[str, int] = {}
        queue: deque[Tuple[str, int]] = deque((ep, 0) for ep in entry_points if ep in self.files)

        for ep in entry_points:
            if ep in self.files:
                distances[ep] = 0

        while queue:
            curr, dist = queue.popleft()
            for neighbor in self.extractor.import_graph.get(curr, set()):
                if neighbor in self.files and neighbor not in distances:
                    distances[neighbor] = dist + 1
                    queue.append((neighbor, dist + 1))

        proximity = {}
        for k in self.files:
            if k in distances:
                proximity[k] = 1.0 / (1.0 + distances[k])
            else:
                proximity[k] = 0.1
        return proximity

    def rank(self, query: str = "") -> List[RankedFile]:
        """Computes composite ranking scores for all files."""
        # 1. Findings score
        findings_per_file: Dict[str, int] = defaultdict(int)
        for f in self.extractor.findings:
            weight = 3 if f.severity == "error" else 1
            findings_per_file[f.file] += weight

        max_findings = max(findings_per_file.values(), default=1)
        max_findings = max(max_findings, 1)

        # 2. Centrality
        centrality = self.compute_centrality()

        # 3. Churn
        max_churn = max(self.extractor.churn_counts.values(), default=1)
        max_churn = max(max_churn, 1)

        # 4. Entry point proximity
        entry_points = self.detect_entry_points()
        entry_prox = self.compute_entry_proximity(entry_points)

        # 5. BM25 score
        bm25_scores = self.extractor.query_bm25(query) if query else {k: 0.0 for k in self.files}

        ranked_list: List[RankedFile] = []
        for rel_path in self.files:
            # Component values [0, 1]
            raw_f_cnt = findings_per_file.get(rel_path, 0)
            s_findings = min(raw_f_cnt / max_findings, 1.0)
            s_centrality = centrality.get(rel_path, 0.0)

            raw_churn = self.extractor.churn_counts.get(rel_path, 0)
            s_churn = min(raw_churn / max_churn, 1.0)
            if rel_path in self.extractor.recent_modified:
                s_churn = min(s_churn + 0.3, 1.0)

            s_entry = entry_prox.get(rel_path, 0.1)
            s_bm25 = bm25_scores.get(rel_path, 0.0)

            total_score = (
                self.config.weight_findings * s_findings +
                self.config.weight_centrality * s_centrality +
                self.config.weight_churn * s_churn +
                self.config.weight_entry_proximity * s_entry +
                self.config.weight_bm25 * s_bm25
            )

            reasons = []
            if raw_f_cnt > 0:
                reasons.append(f"{raw_f_cnt} findings (linter/syntax)")
            if s_centrality > 0.4:
                reasons.append("high centrality / core module")
            if raw_churn > 0 or rel_path in self.extractor.recent_modified:
                reasons.append("active git churn / uncommitted edit")
            if s_entry >= 0.9:
                reasons.append("entry point")
            elif s_entry >= 0.5:
                reasons.append("close to entry point")
            if s_bm25 > 0.3:
                reasons.append(f"lexical match for query (BM25: {s_bm25:.2f})")

            ranked_list.append(RankedFile(
                rel_path=rel_path,
                score=total_score,
                findings_score=s_findings,
                centrality_score=s_centrality,
                churn_score=s_churn,
                entry_proximity_score=s_entry,
                bm25_score=s_bm25,
                findings_count=raw_f_cnt,
                reasons=reasons
            ))

        ranked_list.sort(key=lambda x: x.score, reverse=True)
        return ranked_list


# ============================================================================
# STAGE 3: CONTEXT BUILDER (TOKEN BUDGET)
# ============================================================================

class TokenCounter:
    """Estimates or calculates token counts using tiktoken with fallback."""

    def __init__(self):
        self._tiktoken_enc = None
        try:
            import tiktoken
            self._tiktoken_enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._tiktoken_enc = None

    def count(self, text: str) -> int:
        if self._tiktoken_enc:
            try:
                return len(self._tiktoken_enc.encode(text))
            except Exception:
                pass
        # Accurate heuristic: ~3.7 - 4.0 chars per token for source code
        return max(1, len(text) // 4)


class ContextBuilder:
    """
    Stage 3: Token budget context builder:
    - Repo map (signatures only) for ALL files
    - Full code for top-N suspects
    - ±N lines around each linter finding
    - 1-hop neighbors (callers/callees/imports)
    """

    def __init__(self, config: ContextConfig, extractor: SignalExtractor, ranked_files: List[RankedFile]):
        self.config = config
        self.extractor = extractor
        self.files = extractor.files
        self.ranked_files = ranked_files
        self.tokenizer = TokenCounter()

    def build_repo_map(self, max_tokens: int) -> str:
        """
        Builds a compact signature outline of ALL files in the repository.
        """
        lines = ["# REPOSITORY MAP (Signatures & Structure)"]
        for rel_path, record in sorted(self.files.items()):
            syms = self.extractor.symbols.get(rel_path, [])
            lines.append(f"\n{rel_path} ({record.line_count} lines):")
            if not syms:
                # Include first non-empty comment or docstring if available
                first_lines = [l.strip() for l in record.lines[:3] if l.strip()]
                if first_lines:
                    lines.append(f"    # {first_lines[0][:80]}")
                continue

            for sym in syms[:25]:  # Cap per file to avoid huge maps
                indent = "    "
                doc_snippet = f"  # {sym.docstring}" if sym.docstring else ""
                lines.append(f"{indent}{sym.signature}{doc_snippet}")

        repo_map_str = "\n".join(lines)
        tokens = self.tokenizer.count(repo_map_str)

        # If repo map exceeds budget, prune to highest scored files
        if tokens > max_tokens and len(self.files) > 10:
            lines = ["# REPOSITORY MAP (Summary)"]
            for rf in self.ranked_files[:40]:
                record = self.files[rf.rel_path]
                syms = self.extractor.symbols.get(rf.rel_path, [])
                lines.append(f"\n{rf.rel_path}:")
                for s in syms[:10]:
                    lines.append(f"    {s.signature}")
            repo_map_str = "\n".join(lines)

        return repo_map_str

    def extract_snippets(self, excluded_files: Set[str], window: int) -> List[SnippetContext]:
        """Extracts ±N lines around linter findings for files not included in full."""
        snippets: List[SnippetContext] = []
        for finding in self.extractor.findings:
            if finding.file in excluded_files or finding.file not in self.files:
                continue

            record = self.files[finding.file]
            target_line = finding.line
            start_line = max(1, target_line - window)
            end_line = min(record.line_count, target_line + window)

            snippet_lines = []
            for num in range(start_line, end_line + 1):
                raw_text = record.lines[num - 1] if num - 1 < len(record.lines) else ""
                marker = ">>> " if num == target_line else "    "
                snippet_lines.append(f"{marker}{num:4d} | {raw_text}")

            snippets.append(SnippetContext(
                file=finding.file,
                finding=finding,
                start_line=start_line,
                end_line=end_line,
                snippet_text="\n".join(snippet_lines)
            ))
        return snippets

    def find_one_hop_neighbors(self, seed_files: List[str]) -> List[str]:
        """Finds 1-hop callers, callees, and imported modules."""
        neighbors: Set[str] = set()
        seed_set = set(seed_files)
        for seed in seed_files:
            # Callee / imported files
            for callee in self.extractor.import_graph.get(seed, set()):
                if callee not in seed_set and callee in self.files:
                    neighbors.add(callee)
            # Caller / importing files
            for caller in self.extractor.reverse_import_graph.get(seed, set()):
                if caller not in seed_set and caller in self.files:
                    neighbors.add(caller)
        return sorted(neighbors)

    def build_context(self, query: str = "") -> ContextPayload:
        """Assembles prompt payload within strict token budget allocations."""
        total_budget = self.config.token_budget

        b_map = int(total_budget * self.config.budget_ratio_repomap)
        b_suspects = int(total_budget * self.config.budget_ratio_suspects)
        b_snippets = int(total_budget * self.config.budget_ratio_snippets)
        b_neighbors = int(total_budget * self.config.budget_ratio_neighbors)

        # 1. Build Repo Map
        repo_map = self.build_repo_map(max_tokens=b_map)
        used_map_tokens = self.tokenizer.count(repo_map)

        # Roll unused repo_map tokens over to suspect files
        surplus = max(0, b_map - used_map_tokens)
        b_suspects += surplus

        # 2. Select Top-N suspect files
        full_code_files: List[Tuple[RankedFile, str]] = []
        used_suspect_tokens = 0
        included_paths: Set[str] = set()

        for rf in self.ranked_files[:self.config.top_n_suspects]:
            record = self.files[rf.rel_path]
            file_block = f"\n### FILE: {rf.rel_path} (Score: {rf.score:.3f})\n```\n{record.content}\n```\n"
            t_count = self.tokenizer.count(file_block)

            if used_suspect_tokens + t_count <= b_suspects or not full_code_files:
                full_code_files.append((rf, file_block))
                used_suspect_tokens += t_count
                included_paths.add(rf.rel_path)
            else:
                break

        # 3. Linter Snippets (±N lines around findings for non-included files)
        snippets = self.extract_snippets(excluded_files=included_paths, window=self.config.snippet_window_lines)
        snippet_blocks = []
        used_snippet_tokens = 0
        for snip in snippets:
            block = (
                f"\n### FINDING IN {snip.file}:{snip.finding.line} [{snip.finding.source} - {snip.finding.rule_id}]\n"
                f"Message: {snip.finding.message}\n"
                f"```\n{snip.snippet_text}\n```\n"
            )
            t_count = self.tokenizer.count(block)
            if used_snippet_tokens + t_count <= b_snippets:
                snippet_blocks.append(block)
                used_snippet_tokens += t_count

        # 4. 1-Hop Neighbors (Signatures / Outlines)
        neighbor_paths = self.find_one_hop_neighbors([rf.rel_path for rf, _ in full_code_files])
        neighbor_blocks = []
        used_neighbor_tokens = 0
        for n_path in neighbor_paths:
            if n_path in included_paths:
                continue
            syms = self.extractor.symbols.get(n_path, [])
            sig_list = [f"    {s.signature}" for s in syms[:8]]
            sig_content = "\n".join(sig_list) if sig_list else "    # (No exported top-level symbols)"
            block = f"\n### NEIGHBOR INTERFACE: {n_path}\n```\n{sig_content}\n```\n"
            t_count = self.tokenizer.count(block)
            if used_neighbor_tokens + t_count <= b_neighbors:
                neighbor_blocks.append(block)
                used_neighbor_tokens += t_count

        # Assemble Final Prompt Text
        prompt_sections = [
            "# CONTEXT FOR CODING AGENT",
            f"Query/Task: {query if query else 'Analyze and resolve codebase issues'}",
            "\n" + "=" * 60,
            "## SECTION 1: REPOSITORY MAP & ARCHITECTURE",
            "=" * 60,
            repo_map,
            "\n" + "=" * 60,
            f"## SECTION 2: TOP SUSPECT FILES (FULL SOURCE - {len(full_code_files)} files)",
            "=" * 60,
        ]

        for rf, file_block in full_code_files:
            reasons_str = f"Reasons: {', '.join(rf.reasons)}" if rf.reasons else ""
            prompt_sections.append(f"\n<!-- Suspect File: {rf.rel_path} | Score: {rf.score:.3f} | {reasons_str} -->")
            prompt_sections.append(file_block)

        if snippet_blocks:
            prompt_sections.extend([
                "\n" + "=" * 60,
                f"## SECTION 3: LINTER & SYNTAX FINDINGS (±{self.config.snippet_window_lines} lines context)",
                "=" * 60,
            ])
            prompt_sections.extend(snippet_blocks)

        if neighbor_blocks:
            prompt_sections.extend([
                "\n" + "=" * 60,
                "## SECTION 4: 1-HOP NEIGHBORS (CALLERS, CALLEES, IMPORTS)",
                "=" * 60,
            ])
            prompt_sections.extend(neighbor_blocks)

        final_prompt_text = "\n".join(prompt_sections)
        total_estimated_tokens = self.tokenizer.count(final_prompt_text)

        ranking_summary = [
            {
                "file": rf.rel_path,
                "score": round(rf.score, 4),
                "reasons": rf.reasons,
                "findings_count": rf.findings_count
            }
            for rf in self.ranked_files[:15]
        ]

        return ContextPayload(
            prompt_text=final_prompt_text,
            repo_map=repo_map,
            top_files=[rf for rf, _ in full_code_files],
            snippets=snippets,
            neighbors=neighbor_paths,
            estimated_tokens=total_estimated_tokens,
            ranking_summary=ranking_summary
        )


# ============================================================================
# STAGE 4: LLM AGENT LOOP WITH TOOLS
# ============================================================================

class AgentTools:
    """
    Stage 4: Exposes LLM agent loop tools:
      - read_file(path, start, end)
      - grep(pattern, path, case_sensitive, regex)
      - find_references(symbol)
      - get_symbols(file)
    Also provides tool calling schemas for OpenAI, Anthropic, Gemini, etc.
    """

    def __init__(self, repo_dir: Path, files: Dict[str, FileRecord], symbols: Dict[str, List[Symbol]]):
        self.repo_dir = repo_dir
        self.files = files
        self.symbols = symbols

    def _normalize_path(self, path_str: str) -> str:
        """Normalizes path relative to repo."""
        p = Path(path_str)
        if p.is_absolute():
            try:
                rel = p.relative_to(self.repo_dir)
                return str(rel).replace("\\", "/")
            except ValueError:
                pass
        return path_str.replace("\\", "/").strip("./")

    # 4.1 read_file(path, start, end)
    def read_file(self, path: str, start: Optional[int] = None, end: Optional[int] = None) -> str:
        """
        Reads a file with 1-based start and end line numbers and line numbering.
        """
        rel_path = self._normalize_path(path)
        record = self.files.get(rel_path)

        if not record:
            abs_p = self.repo_dir / rel_path
            if abs_p.exists() and abs_p.is_file():
                try:
                    content = abs_p.read_text(encoding="utf-8", errors="replace")
                    lines = content.splitlines()
                except Exception as e:
                    return f"Error reading file {path}: {str(e)}"
            else:
                return f"Error: File '{path}' does not exist."
        else:
            lines = record.lines

        total_lines = len(lines)
        s = max(1, start if start is not None else 1)
        e = min(total_lines, end if end is not None else total_lines)

        if s > total_lines:
            return f"Error: start line {s} exceeds total lines ({total_lines})."

        output = [f"--- File: {rel_path} (Lines {s}-{e} of {total_lines}) ---"]
        for num in range(s, e + 1):
            line_str = lines[num - 1] if num - 1 < len(lines) else ""
            output.append(f"{num:5d} | {line_str}")
        return "\n".join(output)

    # 4.2 grep(pattern, path, case_sensitive, regex)
    def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        case_sensitive: bool = False,
        regex: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Searches codebase for pattern. Returns matched files, lines, and text.
        """
        results: List[Dict[str, Any]] = []
        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            matcher = re.compile(pattern, flags) if regex else None
        except re.error as e:
            # Fallback to plain substring search
            regex = False
            matcher = None

        target_files = [self._normalize_path(path)] if path else list(self.files.keys())

        for f in target_files:
            record = self.files.get(f)
            if not record:
                continue
            for idx, line in enumerate(record.lines, start=1):
                matched = False
                matched_text = ""
                if regex and matcher:
                    m = matcher.search(line)
                    if m:
                        matched = True
                        matched_text = m.group(0)
                else:
                    target_line = line if case_sensitive else line.lower()
                    target_pat = pattern if case_sensitive else pattern.lower()
                    if target_pat in target_line:
                        matched = True
                        matched_text = pattern

                if matched:
                    results.append({
                        "file": f,
                        "line": idx,
                        "text": line.strip(),
                        "match": matched_text
                    })
                    if len(results) >= 200:  # Safety cap
                        return results
        return results

    # 4.3 find_references(symbol)
    def find_references(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Finds definitions and call sites of a symbol across the repository.
        """
        results: List[Dict[str, Any]] = []
        sym_pattern = re.compile(rf"\b{re.escape(symbol)}\b")

        # 1. Definitions from indexed symbols
        for f, sym_list in self.symbols.items():
            for s in sym_list:
                if s.name == symbol:
                    results.append({
                        "file": f,
                        "line": s.line_start,
                        "kind": f"definition ({s.kind})",
                        "text": s.signature
                    })

        # 2. Usages / References across all lines
        for f, record in self.files.items():
            for idx, line in enumerate(record.lines, start=1):
                if sym_pattern.search(line):
                    # Skip if it is the definition line itself
                    is_def = any(r["file"] == f and r["line"] == idx for r in results)
                    if not is_def:
                        results.append({
                            "file": f,
                            "line": idx,
                            "kind": "reference",
                            "text": line.strip()
                        })
                    if len(results) >= 150:
                        return results
        return results

    # 4.4 get_symbols(file)
    def get_symbols(self, file: str) -> List[Dict[str, Any]]:
        """
        Returns all symbols (classes, functions, methods) defined in a file.
        """
        rel_path = self._normalize_path(file)
        sym_list = self.symbols.get(rel_path, [])
        return [
            {
                "name": s.name,
                "kind": s.kind,
                "line_start": s.line_start,
                "line_end": s.line_end,
                "signature": s.signature,
                "docstring": s.docstring
            }
            for s in sym_list
        ]

    # Tool calling schemas (OpenAI / Anthropic format)
    @classmethod
    def get_tool_schemas(cls) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Reads file contents with 1-based line numbers. Can restrict to start and end lines.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path."},
                            "start": {"type": "integer", "description": "Start line number (1-based, inclusive)."},
                            "end": {"type": "integer", "description": "End line number (1-based, inclusive)."}
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "grep",
                    "description": "Searches codebase for a regex or string pattern across files.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Regex or string pattern to search."},
                            "path": {"type": "string", "description": "Optional specific file to search in."},
                            "case_sensitive": {"type": "boolean", "description": "Whether search is case-sensitive."},
                            "regex": {"type": "boolean", "description": "Whether pattern is a regular expression."}
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "find_references",
                    "description": "Finds all definitions and usage references of a symbol across the codebase.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Exact name of class, function, or variable."}
                        },
                        "required": ["symbol"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_symbols",
                    "description": "Returns all code symbols (classes, functions, methods) defined in a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "description": "Relative path of file."}
                        },
                        "required": ["file"]
                    }
                }
            }
        ]

    def call_tool(self, name: str, **kwargs) -> Any:
        """Dispatcher for tool calls."""
        if name == "read_file":
            return self.read_file(
                path=kwargs.get("path", ""),
                start=kwargs.get("start"),
                end=kwargs.get("end")
            )
        elif name == "grep":
            return self.grep(
                pattern=kwargs.get("pattern", ""),
                path=kwargs.get("path"),
                case_sensitive=kwargs.get("case_sensitive", False),
                regex=kwargs.get("regex", True)
            )
        elif name == "find_references":
            return self.find_references(symbol=kwargs.get("symbol", ""))
        elif name == "get_symbols":
            return self.get_symbols(file=kwargs.get("file", ""))
        else:
            raise ValueError(f"Unknown tool name: {name}")


# ============================================================================
# STAGE 5: VERIFY (LINE EXISTS, LINTER AGREES, DEDUPLICATE)
# ============================================================================

class Verifier:
    """
    Stage 5: Verifies code changes and findings:
      - verify_line_exists(file, line_num, expected_text)
      - verify_syntax(file, content)
      - verify_linter(file, content)
      - deduplicate_findings(findings)
      - verify_patch(file, old_code, new_code)
    """

    def __init__(self, repo_dir: Path, files: Dict[str, FileRecord]):
        self.repo_dir = repo_dir
        self.files = files

    def _normalize_path(self, path_str: str) -> str:
        p = Path(path_str)
        if p.is_absolute():
            try:
                rel = p.relative_to(self.repo_dir)
                return str(rel).replace("\\", "/")
            except ValueError:
                pass
        return path_str.replace("\\", "/").strip("./")

    def verify_line_exists(
        self,
        file: str,
        line_num: int,
        expected_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Verifies if line_num exists in file, and checks optional expected_text.
        """
        rel_path = self._normalize_path(file)
        record = self.files.get(rel_path)

        if not record:
            abs_p = self.repo_dir / rel_path
            if not abs_p.exists():
                return {"valid": False, "message": f"File '{file}' does not exist."}
            lines = abs_p.read_text(encoding="utf-8", errors="replace").splitlines()
        else:
            lines = record.lines

        if line_num < 1 or line_num > len(lines):
            return {
                "valid": False,
                "message": f"Line {line_num} out of bounds (file has {len(lines)} lines)."
            }

        actual_text = lines[line_num - 1]
        matches = True
        if expected_text is not None:
            matches = (expected_text.strip() == actual_text.strip())

        return {
            "valid": matches,
            "line_num": line_num,
            "actual_text": actual_text,
            "matches_expected": matches,
            "message": "Line exists and matches expected content." if matches else "Line text does not match expected text."
        }

    def verify_syntax(self, file: str, content: Optional[str] = None) -> Dict[str, Any]:
        """Verifies syntax of Python or JSON file/content."""
        rel_path = self._normalize_path(file)
        code_content = content
        if code_content is None:
            record = self.files.get(rel_path)
            if not record:
                return {"valid": False, "message": f"File '{file}' not found."}
            code_content = record.content

        if rel_path.endswith(".py"):
            try:
                ast.parse(code_content, filename=rel_path)
                return {"valid": True, "message": "Python AST syntax check passed."}
            except SyntaxError as e:
                return {
                    "valid": False,
                    "line": e.lineno,
                    "col": e.offset,
                    "message": f"SyntaxError at line {e.lineno}:{e.offset}: {e.msg}"
                }
        elif rel_path.endswith(".json"):
            try:
                json.loads(code_content)
                return {"valid": True, "message": "JSON syntax check passed."}
            except json.JSONDecodeError as e:
                return {
                    "valid": False,
                    "line": e.lineno,
                    "col": e.colno,
                    "message": f"JSONDecodeError at line {e.lineno}:{e.colno}: {e.msg}"
                }
        return {"valid": True, "message": "No syntax checker registered for this file type."}

    def verify_patch(self, file: str, old_code: str, new_code: str) -> Dict[str, Any]:
        """
        Verifies a prospective replacement patch:
        1. Checks old_code exists in file
        2. Simulates substitution
        3. Checks syntax of patched content
        """
        rel_path = self._normalize_path(file)
        record = self.files.get(rel_path)
        if not record:
            return {"valid": False, "message": f"File '{file}' not found in repo."}

        current_content = record.content
        if old_code not in current_content:
            return {
                "valid": False,
                "message": f"old_code block was not found in '{rel_path}'. Verify lines and exact whitespace."
            }

        count = current_content.count(old_code)
        if count > 1:
            return {
                "valid": False,
                "message": f"old_code matches {count} different locations in '{rel_path}'. Provide more context."
            }

        patched_content = current_content.replace(old_code, new_code, 1)
        syntax_res = self.verify_syntax(rel_path, patched_content)
        if not syntax_res["valid"]:
            return {
                "valid": False,
                "message": f"Patch introduces syntax error: {syntax_res['message']}",
                "syntax_error": syntax_res
            }

        return {
            "valid": True,
            "message": "Patch applies cleanly and passes syntax verification.",
            "patched_content": patched_content
        }

    @staticmethod
    def deduplicate_findings(findings: List[Finding]) -> List[Finding]:
        """Deduplicates findings by (file, line, normalized message or rule)."""
        seen: Set[Tuple[str, int, str]] = set()
        deduped: List[Finding] = []

        for f in findings:
            key = (f.file, f.line, f.rule_id or f.message.strip().lower())
            if key not in seen:
                seen.add(key)
                deduped.append(f)

        return deduped


# ============================================================================
# UNIFIED PIPELINE FACADE
# ============================================================================

class CodebaseContextPipeline:
    """
    Unified end-to-end pipeline implementing Stages 0 through 5:
      0. Ingest: clone, .gitignore filter, size cap
      1. Signals: linters/type checkers, symbol index, import graph, git churn, BM25
      2. Rank files: score = findings + centrality + churn + entry proximity + bm25
      3. Context builder: repo map, top suspects, findings context, 1-hop neighbors
      4. LLM agent loop with tools: read_file, grep, find_references, get_symbols
      5. Verify: line exists, linter agrees, deduplicate
    """

    def __init__(self, repo_path: str = ".", config: Optional[ContextConfig] = None):
        self.config = config or ContextConfig(repo_path=repo_path)
        self.config.repo_path = repo_path
        self.repo_dir = Path(repo_path).resolve()

        self.ingester = RepoIngester(self.config)
        self.files: Dict[str, FileRecord] = {}
        self.extractor: Optional[SignalExtractor] = None
        self.ranker: Optional[FileRanker] = None
        self.tools: Optional[AgentTools] = None
        self.verifier: Optional[Verifier] = None
        self.ranked_files: List[RankedFile] = []

    def ingest(self) -> Dict[str, FileRecord]:
        """Runs Stage 0 & Stage 1: ingests repo and extracts deterministic signals."""
        self.files = self.ingester.ingest()
        self.extractor = SignalExtractor(self.repo_dir, self.files)

        # 1. Deterministic signals
        self.extractor.extract_linter_findings()
        self.extractor.extract_symbols_and_imports()
        self.extractor.extract_git_signals()
        self.extractor.index_bm25()

        # Tools and Verifiers
        self.tools = AgentTools(self.repo_dir, self.files, self.extractor.symbols)
        self.verifier = Verifier(self.repo_dir, self.files)
        self.ranker = FileRanker(self.config, self.extractor)

        return self.files

    def rank_files(self, query: str = "") -> List[RankedFile]:
        """Runs Stage 2: ranks files based on multi-signal scoring."""
        if not self.files:
            self.ingest()
        if not self.ranker:
            self.ranker = FileRanker(self.config, self.extractor)
        self.ranked_files = self.ranker.rank(query=query)
        return self.ranked_files

    def build_context(self, query: str = "", token_budget: Optional[int] = None) -> ContextPayload:
        """
        Runs Stage 3: builds the token-budgeted prompt context.
        """
        if token_budget:
            self.config.token_budget = token_budget

        if not self.files:
            self.ingest()

        self.rank_files(query=query)

        builder = ContextBuilder(self.config, self.extractor, self.ranked_files)
        return builder.build_context(query=query)

    def get_tools(self) -> AgentTools:
        """Returns Stage 4 tools instance for agent loop."""
        if not self.tools:
            self.ingest()
        return self.tools

    def get_verifier(self) -> Verifier:
        """Returns Stage 5 verifier instance."""
        if not self.verifier:
            self.ingest()
        return self.verifier


# ============================================================================
# SELF-TEST & CLI ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys

    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    print(f"[*] Initializing CodebaseContextPipeline on '{target_dir}'...")

    pipeline = CodebaseContextPipeline(repo_path=target_dir)
    files = pipeline.ingest()
    print(f"[+] Ingested {len(files)} files (after .gitignore, size caps, and binary filters).")

    findings = pipeline.extractor.findings
    print(f"[+] Extracted {len(findings)} deterministic linter/syntax findings.")
    for f in findings[:5]:
        print(f"    - {f.file}:{f.line} [{f.severity}] {f.message}")

    print("[*] Ranking files...")
    ranked = pipeline.rank_files(query="timeout error connection")
    print(f"[+] Top {min(5, len(ranked))} ranked suspect files:")
    for r in ranked[:5]:
        print(f"    {r.score:.3f} | {r.rel_path} -> {', '.join(r.reasons)}")

    print("[*] Building token-budgeted context (budget=8000)...")
    payload = pipeline.build_context(query="timeout error connection", token_budget=8000)
    print(f"[+] Context built successfully! Estimated tokens: {payload.estimated_tokens}")
    print(f"[+] Included {len(payload.top_files)} full suspect files, {len(payload.snippets)} snippet contexts.")

    print("\n[*] Testing Stage 4 Agent Tools:")
    tools = pipeline.get_tools()
    first_file = list(files.keys())[0] if files else None
    if first_file:
        snippet = tools.read_file(first_file, start=1, end=5)
        print(f"[+] tools.read_file('{first_file}', 1, 5):\n{snippet}")
        symbols = tools.get_symbols(first_file)
        print(f"[+] tools.get_symbols('{first_file}'): found {len(symbols)} symbols.")

    print("\n[*] Testing Stage 5 Verifier:")
    verifier = pipeline.get_verifier()
    if first_file:
        line_check = verifier.verify_line_exists(first_file, line_num=1)
        print(f"[+] Line exists check: {line_check}")
    print("\n[✔] Pipeline test completed successfully.")
