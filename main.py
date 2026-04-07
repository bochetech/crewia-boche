"""Entry point for the CrewAI Triage Analytical Pipeline.

Modes
-----
demo        Run two built-in sample emails (default).
email       Interactive: type/paste an email and triage it.
chat        Interactive: type a chat message and triage it.
inbox       Enqueue one sample of each channel and poll via run_triage_from_inboxes().
telegram    Start the Telegram bot (requires TELEGRAM_BOT_TOKEN in .env).
meeting     Transcribe + analyse a meeting recording (mp4, m4a, mp3, wav, …).
--email TXT Pass a raw email/message text directly (non-interactive).

Usage
-----
    # Built-in demo
    .venv313/bin/python3 main.py

    # Interactive email mode
    .venv313/bin/python3 main.py --mode email

    # Interactive chat mode
    .venv313/bin/python3 main.py --mode chat

    # Inbox poll demo (email + chat queued together)
    .venv313/bin/python3 main.py --mode inbox

    # Telegram bot (get token from @BotFather, add to .env as TELEGRAM_BOT_TOKEN)
    .venv313/bin/python3 main.py --mode telegram

    # Transcribe + analyse a meeting recording
    .venv313/bin/python3 main.py --mode meeting --file reunion.mp4
    .venv313/bin/python3 main.py --mode meeting --file reunion.mp4 --whisper-model small
    .venv313/bin/python3 main.py --mode meeting --file reunion.mp4 --flow strategy_crew
    .venv313/bin/python3 main.py --mode meeting --file reunion.mp4 --save-only

    # Pass raw text directly
    .venv313/bin/python3 main.py --email "De: x@y.com\\nAsunto: Shopify\\n\\nPropuesta..."
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap

from src.triage_crew import run_triage, run_triage_from_inboxes
from src.input_sources import EmailInboxTool, ChatMessageInboxTool
# ---------------------------------------------------------------------------
# Sample messages for demo / inbox modes
# ---------------------------------------------------------------------------

SAMPLE_STRATEGIC = textwrap.dedent("""\
    De: techpartner@cloudservices.io
    Asunto: Propuesta de integración Shopify + Bókun para e-commerce B2C

    Hola equipo,

    Nos complace presentarles una propuesta para migrar su infraestructura local
    de ticketing hacia una solución SaaS basada en microservicios, integrando
    Bókun como motor de reservas y Shopify como frontend de e-commerce B2C.

    La solución reduciría sus costos de infraestructura en un 40% y mejoraría
    la eficiencia operacional al eliminar servidores on-premise.

    Estimamos una implementación en 8 semanas con soporte dedicado.

    Quedamos atentos a sus comentarios.

    Saludos,
    Partner Team — CloudServices.io
""")

SAMPLE_JUNK = textwrap.dedent("""\
    De: noreply@promosfantasticas.net
    Asunto: ¡Ganaste un iPhone 15 Pro! Reclamalo AHORA

    Estimado usuario,

    Ha sido seleccionado como ganador de nuestro sorteo mensual.
    Haga clic aquí para reclamar su premio antes de que expire.

    No responda a este correo.
""")

SAMPLE_CHAT_STRATEGIC = textwrap.dedent("""\
    Hola, ¿viste la propuesta de integración con Bókun que llegó por mail?
    Creo que deberíamos evaluarla seriamente para el roadmap de e-commerce.
    El CTO quiere una respuesta esta semana.
""")

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

SEPARATOR = "═" * 62


def _print_result(label: str, result: object) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  📨  {label}")
    print(SEPARATOR)
    print(result.model_dump_json(indent=2))  # type: ignore[attr-defined]
    print(SEPARATOR)


def _read_multiline(prompt: str) -> str:
    """Read multi-line input from stdin until the user types END on its own line."""
    print(prompt)
    print("  (Escribe el texto. Cuando termines escribe END en una línea sola y presiona Enter)\n")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def mode_demo() -> None:
    """Run both built-in samples end-to-end."""
    print("\n🔵  Ejecutando pipeline con dos emails de ejemplo…\n")

    r1 = run_triage(SAMPLE_STRATEGIC)
    _print_result("EMAIL 1 — Esperado: STRATEGIC", r1)

    r2 = run_triage(SAMPLE_JUNK)
    _print_result("EMAIL 2 — Esperado: JUNK", r2)

    assert r1.classification == "STRATEGIC", "❌ Email 1 debería ser STRATEGIC"
    assert r2.classification == "JUNK",      "❌ Email 2 debería ser JUNK"
    print("\n✅  Ambos emails clasificados correctamente.\n")


def mode_email_interactive() -> None:
    """Interactive loop: paste an email, triage it, repeat."""
    print("\n📧  MODO EMAIL INTERACTIVO")
    print("   Escribe o pega un email y el agente lo triará.")
    print("   Formato sugerido:")
    print("     De: remitente@ejemplo.com")
    print("     Asunto: Línea de asunto\n")
    print("     Cuerpo del mensaje...")
    print("   (Ctrl+C para salir)\n")

    while True:
        try:
            text = _read_multiline("📩  Nuevo email:")
            if not text.strip():
                print("⚠️  Texto vacío, intenta de nuevo.\n")
                continue
            result = run_triage(text)
            _print_result("Resultado del triage", result)
            print()
        except KeyboardInterrupt:
            print("\n\n👋  Hasta luego.\n")
            break


def mode_chat_interactive() -> None:
    """Interactive loop: type a chat message, triage it, repeat."""
    print("\n💬  MODO CHAT INTERACTIVO")
    print("   Escribe un mensaje de chat (Telegram/Slack) para ser triado.")
    print("   El agente lo normalizará al formato De:/Asunto: internamente.")
    print("   (Ctrl+C para salir)\n")

    sender = input("👤  Tu nombre/alias (ej: @jefe): ").strip() or "@usuario"
    topic  = input("📌  Tema del hilo (ej: 'Integración Shopify'): ").strip() or "(chat)"
    print()

    while True:
        try:
            text = _read_multiline("💬  Mensaje:")
            if not text.strip():
                print("⚠️  Mensaje vacío, intenta de nuevo.\n")
                continue
            # Format as the standard triage input the agent expects
            formatted = (
                f"De: {sender}\n"
                f"Asunto: {topic}\n"
                f"Canal: telegram\n\n"
                f"{text}"
            )
            result = run_triage(formatted)
            _print_result("Resultado del triage", result)
            print()
        except KeyboardInterrupt:
            print("\n\n👋  Hasta luego.\n")
            break


def mode_inbox_demo() -> None:
    """Enqueue one email and one chat message, then poll via run_triage_from_inboxes."""
    print("\n�  MODO INBOX — Encolando mensajes y ejecutando poll...\n")

    # Enqueue samples into the respective inboxes
    eid = EmailInboxTool.enqueue(
        sender="techpartner@cloudservices.io",
        subject="Propuesta Shopify + Bókun",
        body=textwrap.dedent("""\
            Nos complace presentarles una propuesta para migrar su infraestructura
            de ticketing hacia SaaS con microservicios, integrando Bókun y Shopify.
            Reducción de costos estimada: 40%.  Implementación en 8 semanas.
        """),
    )
    cid = ChatMessageInboxTool.enqueue(
        sender="@cto",
        subject="Roadmap e-commerce",
        body=SAMPLE_CHAT_STRATEGIC,
        channel="telegram",
    )
    print(f"  📧  Email encolado   → message_id: {eid}")
    print(f"  💬  Chat encolado    → message_id: {cid}")
    print(f"\n  Procesando {EmailInboxTool.pending_count()} email(s) "
          f"+ {ChatMessageInboxTool.pending_count()} chat(s)...\n")

    results = run_triage_from_inboxes()

    for i, (msg, decision) in enumerate(results, 1):
        channel_icon = "📧" if msg["channel"] == "email" else "💬"
        _print_result(
            f"Mensaje {i}/{len(results)} [{msg['channel']}] {channel_icon}  "
            f"De: {msg['sender']} | {msg['subject']}",
            decision,
        )

    print(f"\n✅  {len(results)} mensaje(s) procesado(s) desde los inboxes.\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def mode_telegram() -> None:
    """Start the Telegram bot via NiaAgent + TelegramChannel (blocking — Ctrl+C to stop)."""
    from dotenv import load_dotenv
    import os
    import asyncio
    import yaml
    from pathlib import Path

    load_dotenv()

    # Load Nia config
    from src.nia.agent import NiaAgent, NiaConfig
    from src.nia.channels.telegram_channel import TelegramChannel, TelegramChannelConfig
    from src.triage_crew import TriageCrew

    nia_cfg = NiaConfig.from_yaml()
    crew = TriageCrew()
    nia = NiaAgent(config=nia_cfg, crew=crew)

    # Load channel config
    nia_yaml = Path("config/nia.yaml")
    channels_raw: dict = {}
    if nia_yaml.exists():
        with open(nia_yaml) as fh:
            channels_raw = (yaml.safe_load(fh) or {}).get("channels", {})

    tg_cfg = TelegramChannelConfig.from_env_and_yaml(channels_raw)
    tg_cfg.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not tg_cfg.token:
        raise EnvironmentError(
            "TELEGRAM_BOT_TOKEN no encontrado.\n"
            "Agrégalo a .env: TELEGRAM_BOT_TOKEN=123456789:ABCdef..."
        )

    channel = TelegramChannel(config=tg_cfg, nia=nia)

    print("\n🤖  Nia — Agente Estratégico | Telegram")
    print("    Iniciando canales…\n")

    channel.run()   # blocking — python-telegram-bot manages its own event loop


# ---------------------------------------------------------------------------
# Meeting mode
# ---------------------------------------------------------------------------

def mode_meeting(
    file: str,
    whisper_model: str = "base",
    flow_id: str | None = None,
    save_only: bool = False,
    output_file: str | None = None,
) -> None:
    """Transcribe and analyse a meeting recording with Whisper + Nia."""
    from pathlib import Path
    from src.nia.agent import NiaAgent, NiaConfig
    from src.nia.channels.meeting_channel import MeetingChannel

    # Build a lightweight NiaAgent (no Telegram token needed)
    nia_cfg = NiaConfig.from_yaml()
    try:
        from src.triage_crew import TriageCrew
        crew = TriageCrew()
    except Exception:
        crew = None

    nia = NiaAgent(config=nia_cfg, crew=crew)
    channel = MeetingChannel(nia=nia, whisper_model=whisper_model)

    result = channel.process(
        file_path=file,
        save_to_memory=True,
        dispatch_flow=bool(flow_id) and not save_only,
        flow_id=flow_id,
    )

    # ── Print to terminal ──────────────────────────────────────────────────
    print(f"\n{SEPARATOR}")
    print(f"  📋  REUNIÓN: {Path(file).stem}")
    print(SEPARATOR)
    print(result.to_markdown())
    print(SEPARATOR)

    # ── Save to file ───────────────────────────────────────────────────────
    out = output_file or (Path(file).stem + "_nia.md")
    Path(out).write_text(result.to_markdown(), encoding="utf-8")
    print(f"\n💾  Informe guardado en: {out}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage Analytical Pipeline")
    parser.add_argument(
        "--mode",
        choices=["demo", "email", "chat", "inbox", "telegram", "meeting"],
        default="demo",
        help=(
            "demo     = dos emails de ejemplo (default)\n"
            "email    = modo interactivo email\n"
            "chat     = modo interactivo chat\n"
            "inbox    = demo encolado + poll\n"
            "telegram = inicia el bot de Telegram (requiere TELEGRAM_BOT_TOKEN en .env)\n"
            "meeting  = transcribe y analiza una grabación de reunión"
        ),
    )
    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Texto crudo del email/mensaje a triár directamente (no interactivo).",
    )
    # Meeting-specific arguments
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="[meeting] Ruta al archivo de audio/video (mp4, m4a, mp3, wav, …).",
    )
    parser.add_argument(
        "--whisper-model",
        type=str,
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="[meeting] Modelo de Whisper a usar (default: base).",
    )
    parser.add_argument(
        "--flow",
        type=str,
        default=None,
        help="[meeting] Flujo de agentes a ejecutar con el transcript (ej: strategy_crew).",
    )
    parser.add_argument(
        "--save-only",
        action="store_true",
        help="[meeting] Sólo guardar en memoria — no ejecutar flujos.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="[meeting] Nombre del archivo de salida Markdown (default: <nombre_archivo>_nia.md).",
    )
    args = parser.parse_args()

    if args.email:
        result = run_triage(args.email)
        _print_result("Email proporcionado por CLI", result)
        return

    if args.mode == "meeting":
        if not args.file:
            parser.error("--mode meeting requiere --file <ruta_al_archivo>")
        mode_meeting(
            file=args.file,
            whisper_model=args.whisper_model,
            flow_id=args.flow,
            save_only=args.save_only,
            output_file=args.output,
        )
        return

    modes = {
        "demo":     mode_demo,
        "email":    mode_email_interactive,
        "chat":     mode_chat_interactive,
        "inbox":    mode_inbox_demo,
        "telegram": mode_telegram,
    }
    modes[args.mode]()


if __name__ == "__main__":
    main()


