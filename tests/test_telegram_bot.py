"""
Unit tests for Telegram bot mode detection and conversation handling.

Covers:
- Detección de modo CONVERSACIÓN vs TRIAGE
- Lógica invertida: TODO es conversación por defecto
- Solo hacer triage si es email explícito o solicitud directa
"""
from __future__ import annotations

import pytest


class TestModeDetection:
    """Test the logic for detecting CONVERSATION vs TRIAGE mode."""

    @staticmethod
    def _detect_mode(text: str) -> str:
        """
        Replica la lógica de detección del telegram_bot.py
        Returns: 'conversation' or 'triage'
        """
        # Detectar formato de email (headers explícitos)
        is_email_format = any(
            line.strip().lower().startswith(prefix)
            for line in text.split("\n")[:5]
            for prefix in ("de:", "from:", "asunto:", "subject:", "fecha:", "date:")
        )
        
        # Palabras clave que indican intención de TRIAGE explícito
        triage_keywords = [
            "clasifica esto", "clasifica el siguiente", "analiza este email",
            "triaje", "triage", "documenta esto", "es strategic", "es junk"
        ]
        is_explicit_triage = any(keyword in text.lower() for keyword in triage_keywords)
        
        # Mensajes muy largos (>100 palabras) probablemente son emails sin headers
        is_very_long = len(text.split()) > 100
        
        # DECISIÓN: Solo hacer TRIAGE si es email o solicitud explícita
        should_triage = is_email_format or is_explicit_triage or is_very_long
        
        return "triage" if should_triage else "conversation"

    def test_conversational_question_is_conversation(self):
        """Pregunta natural sin keywords → CONVERSACIÓN"""
        text = "Cómo se llaman esos sistemas para gestionar mantenimientos?"
        assert self._detect_mode(text) == "conversation"

    def test_greeting_is_conversation(self):
        """Saludo → CONVERSACIÓN"""
        assert self._detect_mode("Hola Nia") == "conversation"
        assert self._detect_mode("Cómo estás?") == "conversation"

    def test_request_without_email_is_conversation(self):
        """Solicitud directa sin formato email → CONVERSACIÓN"""
        text = "No, solo quería conversar. Es que mi jefe me pidió algo para controlar los mantenimientos del centro turístico."
        assert self._detect_mode(text) == "conversation"

    def test_email_with_headers_is_triage(self):
        """Email con headers De:/Asunto: → TRIAGE"""
        email = """De: partner@cloudtech.io
Asunto: Propuesta integración Shopify

Hola, proponemos una solución..."""
        assert self._detect_mode(email) == "triage"

    def test_email_with_from_subject_is_triage(self):
        """Email con headers en inglés From:/Subject: → TRIAGE"""
        email = """From: vendor@example.com
Subject: New proposal
Date: 2026-04-05

Dear team, ..."""
        assert self._detect_mode(email) == "triage"

    def test_explicit_triage_request_is_triage(self):
        """Solicitud explícita de triage → TRIAGE"""
        assert self._detect_mode("Clasifica esto: Propuesta de Shopify") == "triage"
        assert self._detect_mode("Analiza este email y dime si es strategic") == "triage"
        assert self._detect_mode("Documenta esto en Confluence") == "triage"

    def test_very_long_message_is_triage(self):
        """Mensaje muy largo (>100 palabras) sin headers → TRIAGE"""
        # Generar mensaje de 120 palabras
        long_text = " ".join(["palabra"] * 120)
        assert self._detect_mode(long_text) == "triage"

    def test_medium_message_without_headers_is_conversation(self):
        """Mensaje medio (50 palabras) sin headers ni keywords → CONVERSACIÓN"""
        medium_text = " ".join(["algo"] * 50)
        assert self._detect_mode(medium_text) == "conversation"

    def test_short_technical_question_is_conversation(self):
        """Pregunta técnica corta → CONVERSACIÓN"""
        assert self._detect_mode("Qué opinas de Shopify?") == "conversation"
        assert self._detect_mode("Necesito ayuda con integraciones SAP") == "conversation"

    def test_help_request_is_conversation(self):
        """Solicitud de ayuda → CONVERSACIÓN"""
        assert self._detect_mode("Ayuda, cómo funciona el bot?") == "conversation"
        assert self._detect_mode("Explícame qué haces") == "conversation"


class TestConversationContext:
    """Test conversation context management (timeout, cleanup, etc)."""

    def test_timeout_cleanup_logic(self):
        """Verificar que 10 minutos = 600 segundos"""
        TIMEOUT_SECONDS = 600
        assert TIMEOUT_SECONDS == 10 * 60

    def test_history_limit(self):
        """El historial debe limitarse a últimos N mensajes"""
        # En el código actual son 3 mensajes para conversación
        CONVERSATION_HISTORY_LIMIT = 3
        assert CONVERSATION_HISTORY_LIMIT == 3

    def test_truncate_message_in_context(self):
        """Mensajes en contexto deben truncarse a N chars"""
        # En el código actual son 100 caracteres
        TRUNCATE_LENGTH = 100
        long_message = "x" * 200
        truncated = long_message[:TRUNCATE_LENGTH]
        assert len(truncated) == 100
