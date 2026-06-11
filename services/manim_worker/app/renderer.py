"""ManimRenderer — sandbox'tan geçen kodu render eder.

Akış:
  1. /tmp/manim_renders/{task_id}/scene.py  — kodu yaz
  2. subprocess: manim render --quality {q} -o {task_id}.mp4 scene.py SceneName
  3. timeout=settings.manim_render_timeout_seconds (45 sn varsayılan)
  4. başarılıysa mp4 path + duration + size döndür
  5. cleanup her durumda (try/finally)

Quality mapping:
  720p → -ql=False, -qm; manim 0.18: --quality m / l / h / p / k
  480p → l (low,   480p15)
  720p → m (medium,720p30)
  1080p→ h (high,  1080p60)
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)


_QUALITY_FLAG = {
    "480p": "l",
    "720p": "m",
    "1080p": "h",
}


@dataclass
class RenderResult:
    mp4_path: str
    duration_seconds: float
    file_size_bytes: int


class RenderError(Exception):
    """Manim render sırasında oluşan hata (timeout dahil)."""

    def __init__(self, message: str, traceback_snippet: str = "", is_timeout: bool = False):
        super().__init__(message)
        self.message = message
        self.traceback_snippet = traceback_snippet
        self.is_timeout = is_timeout


class ManimRenderer:
    def __init__(self, temp_dir: str, default_timeout_seconds: int = 45):
        self._base_dir = temp_dir
        self._default_timeout = default_timeout_seconds
        os.makedirs(self._base_dir, exist_ok=True)

    # ─── Public ────────────────────────────────────────────────────

    def render(
        self,
        code: str,
        task_id: str,
        quality: str = "720p",
        timeout_seconds: int | None = None,
    ) -> RenderResult:
        timeout = timeout_seconds or self._default_timeout
        q_flag = _QUALITY_FLAG.get(quality, "m")

        work_dir = os.path.join(self._base_dir, task_id)
        os.makedirs(work_dir, exist_ok=True)
        scene_path = os.path.join(work_dir, "scene.py")
        with open(scene_path, "w", encoding="utf-8") as f:
            f.write(code)

        scene_name = self._extract_first_scene_name(code) or "RavelLesson"
        out_filename = f"{task_id}.mp4"

        cmd = [
            "manim", "render",
            f"-q{q_flag}",                     # -ql / -qm / -qh
            "--media_dir", work_dir,
            "--output_file", out_filename,
            "--disable_caching",               # her render fresh
            "--verbosity", "WARNING",
            scene_path,
            scene_name,
        ]

        try:
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                )
            except subprocess.TimeoutExpired as e:
                raise RenderError(
                    f"manim render timed out after {timeout}s",
                    traceback_snippet=(e.stderr or "")[-500:] if hasattr(e, "stderr") else "",
                    is_timeout=True,
                )

            if proc.returncode != 0:
                snippet = (proc.stderr or proc.stdout or "").strip()
                raise RenderError(
                    f"manim returned rc={proc.returncode}",
                    traceback_snippet=snippet[-1500:],
                )

            mp4_path = self._find_output_mp4(work_dir, out_filename)
            if mp4_path is None or not os.path.exists(mp4_path):
                snippet = (proc.stdout or "")[-500:] + "\n---\n" + (proc.stderr or "")[-500:]
                raise RenderError(
                    "manim succeeded but output mp4 not found",
                    traceback_snippet=snippet,
                )

            size = os.path.getsize(mp4_path)
            duration = _ffprobe_duration_seconds(mp4_path)
            logger.info(
                "rendered task=%s mp4=%s size=%dB duration=%.2fs",
                task_id, mp4_path, size, duration,
            )

            # mp4'ü temp/{task_id}.mp4'e taşı (work_dir tamamen silinmeden önce
            # caller'ın upload edebilmesi için).
            final_path = os.path.join(self._base_dir, out_filename)
            shutil.move(mp4_path, final_path)
            return RenderResult(
                mp4_path=final_path,
                duration_seconds=duration,
                file_size_bytes=size,
            )
        finally:
            # work_dir tamamen sil (başarılı/başarısız her durumda).
            shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def cleanup_mp4(path: str) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            logger.debug("cleanup_mp4 leftover at %s", path)

    # ─── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _extract_first_scene_name(code: str) -> str | None:
        """`class Foo(Scene):` → 'Foo'. Manim CLI hangi scene'i render edeceğini
        bilmek istiyor; ilk Scene subclass'ını alıyoruz."""
        m = re.search(r"^\s*class\s+([A-Za-z_]\w*)\s*\(\s*Scene\s*\)\s*:", code, re.MULTILINE)
        return m.group(1) if m else None

    @staticmethod
    def _find_output_mp4(work_dir: str, filename: str) -> str | None:
        """Manim media tree: <media_dir>/videos/<scene_file>/<quality>/<filename>.
        Önce literal yol; bulamazsak rglob fallback.
        """
        for root, _dirs, files in os.walk(work_dir):
            for f in files:
                if f == filename:
                    return os.path.join(root, f)
        return None


def _ffprobe_duration_seconds(mp4_path: str) -> float:
    """ffprobe ile süre ölç. Bulunamazsa 0.0 döndür."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                mp4_path,
            ],
            stderr=subprocess.STDOUT, timeout=10, text=True,
        )
        return float(out.strip())
    except Exception:
        logger.debug("ffprobe failed for %s — duration=0.0", mp4_path)
        return 0.0
