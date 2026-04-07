"""
MeetingChannel — Transcribe y analiza grabaciones de reuniones.

Flujo:
  1. Recibe un archivo de audio/video (mp4, m4a, mp3, wav, ogg, …)
  2. Extrae el audio si es video (ffmpeg)
  3. Transcribe con Whisper (local, sin enviar datos a la nube)
  4. Genera resumen ejecutivo con NiaAgent.summarize()
  5. Identifica temas y decisiones clave
  6. Guarda en memoria episódica (ChromaDB)
  7. Opcionalmente despacha al flujo de estrategia (strategy_crew)

Uso desde CLI:
    python3 main.py --mode meeting --file reunion.mp4
    python3 main.py --mode meeting --file reunion.mp4 --save-only
    python3 main.py --mode meeting --file reunion.mp4 --notify-telegram
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Audio formats Whisper can handle directly (no ffmpeg extraction needed)
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma"}
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"}


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class MeetingResult:
    """Full output of processing one meeting recording."""
    source_file: str
    duration_seconds: float = 0.0
    transcript: str = ""
    summary: str = ""
    key_topics: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    language: str = "es"
    # If dispatched to a crew flow:
    flow_result: Optional[Any] = None
    flow_id: Optional[str] = None

    def to_markdown(self) -> str:
        """Format result as clean Markdown for Telegram or file output."""
        lines = [
            f"# 📋 Reunión: {Path(self.source_file).stem}",
            f"*Duración:* {int(self.duration_seconds // 60)}m {int(self.duration_seconds % 60)}s",
            f"*Idioma detectado:* {self.language}",
            "",
            "## 📝 Resumen ejecutivo",
            self.summary,
        ]

        if self.key_topics:
            lines += ["", "## 🏷️ Temas principales"]
            for t in self.key_topics:
                lines.append(f"- {t}")

        if self.decisions:
            lines += ["", "## ✅ Decisiones tomadas"]
            for d in self.decisions:
                lines.append(f"- {d}")

        if self.action_items:
            lines += ["", "## 🎯 Acciones pendientes"]
            for a in self.action_items:
                lines.append(f"- {a}")

        if self.transcript:
            lines += [
                "",
                "## 📄 Transcripción completa",
                "```",
                self.transcript[:8000] + ("…" if len(self.transcript) > 8000 else ""),
                "```",
            ]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# MeetingChannel
# ---------------------------------------------------------------------------

class MeetingChannel:
    """
    Processes a meeting recording file through Nia's analysis pipeline.

    Parameters
    ----------
    nia:
        NiaAgent instance.
    whisper_model:
        Whisper model size: "tiny", "base", "small", "medium", "large".
        "base" is a good balance of speed and accuracy for Spanish.
    language:
        Force transcription language. None = auto-detect.
    """

    def __init__(
        self,
        nia: Any,
        whisper_model: str = "base",
        language: Optional[str] = "es",
    ) -> None:
        self.nia = nia
        self.whisper_model = whisper_model
        self.language = language

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        file_path: str | Path,
        save_to_memory: bool = True,
        dispatch_flow: bool = False,
        flow_id: Optional[str] = None,
        meeting_title: Optional[str] = None,
    ) -> MeetingResult:
        """
        Full pipeline: extract → transcribe → analyse → (optionally) dispatch.

        Parameters
        ----------
        file_path:
            Path to the recording file (mp4, m4a, mp3, wav, …).
        save_to_memory:
            Save transcript + summary to ChromaDB for later recall.
        dispatch_flow:
            If True, also dispatch to a crew flow (e.g. strategy_crew).
        flow_id:
            Which flow to run. Defaults to nia.config.default_flow.
        meeting_title:
            Optional title override. Defaults to filename stem.
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Recording not found: {path}")

        title = meeting_title or path.stem
        logger.info("[MeetingChannel] Processing: %s", path.name)

        # Step 1: Extract audio if video
        audio_path = self._extract_audio(path)

        try:
            # Step 2: Transcribe
            print(f"🎙️  Transcribiendo '{path.name}'…  (modelo: {self.whisper_model})")
            transcript, duration, detected_lang = self._transcribe(audio_path)
            print(f"✅  Transcripción lista — {int(duration // 60)}m {int(duration % 60)}s | {len(transcript)} chars")

            # Step 3: Analyse with Nia
            print("🧠  Analizando con Nia…")
            summary, topics, decisions, actions = self._analyse(transcript, title)

            result = MeetingResult(
                source_file=str(path),
                duration_seconds=duration,
                transcript=transcript,
                summary=summary,
                key_topics=topics,
                decisions=decisions,
                action_items=actions,
                language=detected_lang,
            )

            # Step 4: Save to memory
            if save_to_memory:
                self._save_to_memory(result, title)

            # Step 5: Dispatch to flow
            if dispatch_flow:
                fid = flow_id or self.nia.config.default_flow
                print(f"🚀  Despachando al flujo '{fid}'…")
                try:
                    flow_input = self._build_flow_input(result, title)
                    result.flow_result = self.nia.run_flow(fid, flow_input)
                    result.flow_id = fid
                    print(f"✅  Flujo completado")
                except Exception as exc:
                    logger.error("[MeetingChannel] Flow dispatch failed: %s", exc)

            return result

        finally:
            # Clean up temp audio file if we extracted it
            if audio_path != path and audio_path.exists():
                audio_path.unlink()

    async def process_async(self, file_path: str | Path, **kwargs) -> MeetingResult:
        """Async wrapper — runs process() in a thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.process(file_path, **kwargs))

    # ------------------------------------------------------------------
    # Private: audio extraction
    # ------------------------------------------------------------------

    def _extract_audio(self, path: Path) -> Path:
        """If path is a video, extract audio track to a temp WAV file."""
        suffix = path.suffix.lower()

        if suffix in _AUDIO_EXTENSIONS:
            return path   # already audio, no extraction needed

        if suffix not in _VIDEO_EXTENSIONS:
            logger.warning("[MeetingChannel] Unknown extension '%s' — trying anyway", suffix)

        # Extract with ffmpeg to a temp file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        out_path = Path(tmp.name)

        logger.info("[MeetingChannel] Extracting audio from %s → %s", path.name, out_path.name)
        print(f"🎬  Extrayendo audio de '{path.name}'…")

        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(path),
                    "-vn",                    # no video
                    "-acodec", "pcm_s16le",   # WAV PCM
                    "-ar", "16000",           # 16kHz (Whisper native rate)
                    "-ac", "1",               # mono
                    str(out_path),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg error:\n{result.stderr[-500:]}")
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg no encontrado. Instálalo con: brew install ffmpeg"
            )

        return out_path

    # ------------------------------------------------------------------
    # Private: transcription
    # ------------------------------------------------------------------

    def _transcribe(self, audio_path: Path) -> tuple[str, float, str]:
        """
        Transcribe audio with Whisper.

        Returns (transcript_text, duration_seconds, detected_language).
        """
        import whisper  # noqa: PLC0415

        logger.info("[MeetingChannel] Loading Whisper model '%s'", self.whisper_model)
        model = whisper.load_model(self.whisper_model)

        options: dict[str, Any] = {
            "fp16": False,
            "verbose": False,
        }
        if self.language:
            options["language"] = self.language

        result = model.transcribe(str(audio_path), **options)

        # Build full transcript from segments (includes timestamps if needed)
        segments = result.get("segments", [])
        duration = segments[-1]["end"] if segments else 0.0
        detected_lang = result.get("language", self.language or "?")

        # Plain text transcript
        transcript = result["text"].strip()

        # Optionally build timestamped version for long meetings
        if duration > 600:  # > 10 min → add timestamps every ~5 min
            stamped_lines = []
            prev_stamp = -1
            for seg in segments:
                stamp_min = int(seg["start"] // 300) * 5
                if stamp_min != prev_stamp:
                    stamped_lines.append(
                        f"\n[{int(seg['start'] // 60):02d}:{int(seg['start'] % 60):02d}]"
                    )
                    prev_stamp = stamp_min
                stamped_lines.append(seg["text"])
            transcript = "".join(stamped_lines).strip()

        return transcript, duration, detected_lang

    # ------------------------------------------------------------------
    # Private: analysis
    # ------------------------------------------------------------------

    def _analyse(
        self,
        transcript: str,
        title: str,
    ) -> tuple[str, list[str], list[str], list[str]]:
        """
        Use NiaAgent + LLM to extract summary, topics, decisions, actions.
        Returns (summary, topics, decisions, action_items).
        """
        if self.nia.crew is None:
            # No LLM available — return truncated transcript as summary
            return transcript[:500], [], [], []

        # Build a structured prompt
        prompt = f"""Eres Nia, analista estratégica. Analiza la siguiente transcripción de una reunión titulada "{title}".

Responde EXACTAMENTE en este formato JSON (sin markdown, solo JSON):
{{
  "resumen": "Resumen ejecutivo en 3-5 oraciones.",
  "temas": ["tema1", "tema2", "tema3"],
  "decisiones": ["decisión1", "decisión2"],
  "acciones": ["acción pendiente 1 (responsable si se menciona)", "acción 2"]
}}

TRANSCRIPCIÓN:
{transcript[:6000]}"""

        try:
            raw = self.nia.crew.kickoff_conversation(
                user_text=prompt,
                history=[],
                user_id="__meeting__",
            )

            # Parse JSON from response
            import json, re  # noqa: PLC0415
            # Extract JSON block if the model wrapped it in markdown
            json_match = re.search(r'\{.*\}', str(raw), re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return (
                    data.get("resumen", ""),
                    data.get("temas", []),
                    data.get("decisiones", []),
                    data.get("acciones", []),
                )
        except Exception as exc:
            logger.warning("[MeetingChannel] LLM analysis failed: %s — falling back to summarize()", exc)

        # Fallback: use NiaAgent.summarize()
        summary = self.nia.summarize(transcript, max_chars=500)
        return summary, [], [], []

    # ------------------------------------------------------------------
    # Private: memory + flow input
    # ------------------------------------------------------------------

    def _save_to_memory(self, result: MeetingResult, title: str) -> None:
        """Save transcript and summary to ChromaDB under a meeting topic."""
        try:
            from src.conversation_memory import create_user_memory  # noqa: PLC0415
            memory = create_user_memory(
                user_id="__meetings__",
                max_topics=self.nia.config.memory_max_topics,
            )
            # Save summary as assistant message (searchable)
            memory.add_message(
                content=f"[REUNIÓN: {title}]\n\n{result.summary}",
                role="assistant",
                metadata={
                    "source": "meeting",
                    "file": Path(result.source_file).name,
                    "duration": result.duration_seconds,
                    "topics": ", ".join(result.key_topics),
                },
            )
            # Save full transcript as user message
            if result.transcript:
                memory.add_message(
                    content=result.transcript[:3000],
                    role="user",
                    metadata={"source": "meeting_transcript", "title": title},
                )
            print(f"💾  Guardado en memoria episódica (cajón 'reuniones')")
            logger.info("[MeetingChannel] Saved to ChromaDB: %s", title)
        except Exception as exc:
            logger.warning("[MeetingChannel] Could not save to memory: %s", exc)

    def _build_flow_input(self, result: MeetingResult, title: str) -> str:
        """Build the triage input text for crew flow dispatch."""
        parts = [
            f"De: reunión grabada",
            f"Asunto: Análisis de reunión — {title}",
            f"Canal: meeting",
            "",
            f"RESUMEN EJECUTIVO:",
            result.summary,
        ]
        if result.key_topics:
            parts += ["", "TEMAS:", *[f"- {t}" for t in result.key_topics]]
        if result.decisions:
            parts += ["", "DECISIONES:", *[f"- {d}" for d in result.decisions]]
        if result.action_items:
            parts += ["", "ACCIONES PENDIENTES:", *[f"- {a}" for a in result.action_items]]
        parts += ["", "TRANSCRIPCIÓN (primeros 2000 chars):", result.transcript[:2000]]
        return "\n".join(parts)


__all__ = ["MeetingChannel", "MeetingResult"]
