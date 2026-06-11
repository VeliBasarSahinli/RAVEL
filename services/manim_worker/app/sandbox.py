"""Sandbox doğrulayıcısı — çift katman güvenlik (ADR-017).

Katman 1 — AST analizi (pure Python, hızlı):
  - import whitelist: yalnızca {manim, numpy, math, random} ve bunların alt modülleri
  - ast.Call yasakları: exec, eval, compile, open(write mode), __import__
  - ast.Attribute yasakları: __class__, __subclasses__, __globals__, __builtins__
  Yasak pattern bulunursa ValidationError fırlat (satır + neden).

Katman 2 — Subprocess izolasyonu:
  - Kodu geçici .py dosyasına yaz.
  - python -c "import ast, py_compile; ast.parse(open(file).read()); py_compile.compile(file, doraise=True)"
  - timeout=settings.sandbox_syntax_check_timeout_seconds (varsayılan 5 sn)
  - Hata varsa SandboxError; traceback dahil.
  - Manim'i import ETMEZ — sadece syntax check (ADR-017 gereği).

Çıktı: ValidationResult (is_valid + error_type + error_message + traceback).
"""
from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Literal, Optional

logger = logging.getLogger(__name__)

ErrorType = Literal["AST_VIOLATION", "SYNTAX_ERROR", "TIMEOUT", "UNKNOWN"]


@dataclass
class ValidationResult:
    is_valid: bool
    error_type: Optional[ErrorType] = None
    error_message: Optional[str] = None
    traceback_snippet: Optional[str] = None
    cleaned_code: Optional[str] = None  # strip sonrası kod (renderer bunu kullansın)


# ─── Yasak listeler (whitelist'e ek olarak çağrı/öznitelik denetimi) ─

_FORBIDDEN_CALLS = frozenset(
    {"exec", "eval", "compile", "__import__", "input", "breakpoint"}
)
_FORBIDDEN_ATTRS = frozenset(
    {
        "__class__",
        "__subclasses__",
        "__bases__",
        "__mro__",
        "__globals__",
        "__builtins__",
        "__import__",
        "__getattribute__",
    }
)


def _root(name: str) -> str:
    """'numpy.linalg' → 'numpy' — whitelist sadece root modüle bakıyor."""
    return (name or "").split(".", 1)[0]


# Defansif markdown fence stripper — orchestrator'da bir kez yapıldı, ama
# başka kaynaklardan gelen kod (DLQ replay, manuel test) için burada da
# uygulayalım. Production'da girdi her zaman strip edilmiş kod olmalı.
_FENCE_OPEN_RE = re.compile(r"^\s*```(?:python|py)?\s*\n", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\n```\s*$")
_CODE_PREFIX = ("from ", "import ", "class ", "def ", "@", "#", "if __name__")


def _strip_code_fence(code: str) -> str:
    if not code:
        return code
    s = code.strip()
    s = _FENCE_OPEN_RE.sub("", s, count=1)
    s = _FENCE_CLOSE_RE.sub("", s)
    s = s.strip()
    lines = s.splitlines()
    code_start = 0
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped:
            continue
        if stripped.startswith(_CODE_PREFIX):
            code_start = i
            break
    if code_start > 0:
        s = "\n".join(lines[code_start:])
    return s.strip()


# manim_code.yaml prompt'u Türkçe karakterleri yasaklıyor (LaTeX/font hatası
# önlemek için), ama LLM yine de bazen ş/ğ/ü/ö/ç/ı üretiyor. Sandbox AST ve
# syntax kontrolünden geçer (string literal'lar parse edilir), ama Manim
# render'da MathTex/Tex LaTeX'e gidip ASCII dışı karakterde fail ediyor.
# Defansif olarak burada ASCII-fold uyguluyoruz.
_TR_MAP = str.maketrans("şğüöçıŞĞÜÖÇİ", "sguociSGUOCI")


def _sanitize_turkish(code: str) -> str:
    """Manim LaTeX renderında Türkçe karakter hata verir — ASCII'ye çevir."""
    return code.translate(_TR_MAP)


class SandboxValidator:
    def __init__(self, allowed_imports: list[str], syntax_timeout_seconds: int = 5):
        self._allowed = frozenset(_root(x) for x in allowed_imports if x.strip())
        self._timeout = max(1, syntax_timeout_seconds)
        logger.info(
            "Sandbox initialized — whitelist=%s timeout=%ds",
            sorted(self._allowed), self._timeout,
        )

    # ─── Public API ─────────────────────────────────────────────────

    def validate(self, code: str) -> ValidationResult:
        # 0. Defansif normalize:
        #    a) markdown fence/önek strip
        #    b) Türkçe karakterleri ASCII'ye çevir (LaTeX render güvenliği)
        code = _strip_code_fence(code)
        code = _sanitize_turkish(code)

        # 1. AST analizi
        ast_result = self._validate_ast(code)
        if not ast_result.is_valid:
            ast_result.cleaned_code = code
            return ast_result

        # 2. Subprocess syntax check (Manim'i load etmez)
        sub_result = self._validate_syntax_subprocess(code)
        sub_result.cleaned_code = code
        return sub_result

    # ─── Katman 1: AST ──────────────────────────────────────────────

    def _validate_ast(self, code: str) -> ValidationResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationResult(
                is_valid=False,
                error_type="SYNTAX_ERROR",
                error_message=f"AST parse failed: {e.msg} (line {e.lineno})",
                traceback_snippet=str(e),
            )

        for node in ast.walk(tree):
            # ── Import denetimi (whitelist) ──
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = _root(alias.name)
                    if root not in self._allowed:
                        return self._violation(
                            node,
                            f"import '{alias.name}' not in whitelist {sorted(self._allowed)}",
                        )

            elif isinstance(node, ast.ImportFrom):
                # 'from manim import *' → module='manim'; relative import → module=None
                if node.module is None or node.level > 0:
                    return self._violation(node, "relative imports are not allowed")
                root = _root(node.module)
                if root not in self._allowed:
                    return self._violation(
                        node,
                        f"from '{node.module}' import — not in whitelist "
                        f"{sorted(self._allowed)}",
                    )

            # ── Yasak çağrılar ──
            elif isinstance(node, ast.Call):
                func = node.func
                # exec / eval / compile / __import__ / input / breakpoint
                if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALLS:
                    return self._violation(node, f"forbidden call: {func.id}()")
                # open(...) — write mode'u argüman olarak geliyorsa engelle
                if isinstance(func, ast.Name) and func.id == "open":
                    return self._violation(node, "forbidden call: open() — file I/O blocked")

            # ── Yasak özellikler ──
            elif isinstance(node, ast.Attribute):
                if node.attr in _FORBIDDEN_ATTRS:
                    return self._violation(node, f"forbidden attribute: .{node.attr}")

            # ── Tehlikeli isim erişimleri (Name düzeyinde) ──
            elif isinstance(node, ast.Name):
                if node.id in {"__import__", "__builtins__"}:
                    return self._violation(node, f"forbidden name reference: {node.id}")

        return ValidationResult(is_valid=True)

    @staticmethod
    def _violation(node: ast.AST, msg: str) -> ValidationResult:
        line = getattr(node, "lineno", "?")
        return ValidationResult(
            is_valid=False,
            error_type="AST_VIOLATION",
            error_message=f"line {line}: {msg}",
            traceback_snippet=None,
        )

    # ─── Katman 2: Subprocess syntax check ──────────────────────────

    def _validate_syntax_subprocess(self, code: str) -> ValidationResult:
        """py_compile ile compile-only check.

        Manim'i import etmez; saf Python AST + bytecode compile.
        Subprocess izolasyonu çünkü compile() bile theoretically yan etki
        yapabilir (rare edge case, defensive).
        """
        tmp_dir = tempfile.mkdtemp(prefix="ravel_sandbox_")
        scene_path = os.path.join(tmp_dir, "scene.py")
        try:
            with open(scene_path, "w", encoding="utf-8") as f:
                f.write(code)

            check_cmd = [
                sys.executable,
                "-c",
                (
                    "import ast, py_compile, sys\n"
                    "p = sys.argv[1]\n"
                    "with open(p, 'r', encoding='utf-8') as f:\n"
                    "    src = f.read()\n"
                    "ast.parse(src)\n"
                    "py_compile.compile(p, doraise=True)\n"
                ),
                scene_path,
            ]
            try:
                proc = subprocess.run(
                    check_cmd,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
            except subprocess.TimeoutExpired:
                return ValidationResult(
                    is_valid=False,
                    error_type="TIMEOUT",
                    error_message=f"syntax check timed out (>{self._timeout}s)",
                )

            if proc.returncode == 0:
                return ValidationResult(is_valid=True)

            stderr_tail = (proc.stderr or "").strip().splitlines()
            snippet = "\n".join(stderr_tail[-10:]) if stderr_tail else "<no stderr>"
            return ValidationResult(
                is_valid=False,
                error_type="SYNTAX_ERROR",
                error_message=f"py_compile rejected the script (rc={proc.returncode})",
                traceback_snippet=snippet,
            )
        finally:
            try:
                if os.path.exists(scene_path):
                    os.remove(scene_path)
                pyc_dir = os.path.join(tmp_dir, "__pycache__")
                if os.path.isdir(pyc_dir):
                    for f in os.listdir(pyc_dir):
                        os.remove(os.path.join(pyc_dir, f))
                    os.rmdir(pyc_dir)
                os.rmdir(tmp_dir)
            except Exception:
                logger.debug("sandbox cleanup leftover at %s", tmp_dir)
