#!/usr/bin/env python3
"""
Test: Verificar que TriageCrew usa LM Studio como prioridad.

Este script verifica el orden de prioridad de LLMs:
1. LM Studio local (si está disponible)
2. Gemini API (fallback)
3. Stub mode (tests)
"""

import os
import sys

# Asegurar que LM Studio esté configurado
os.environ['LMSTUDIO_BASE_URL'] = 'http://localhost:1234/v1'

from src.triage_crew import TriageCrew

def test_llm_priority():
    """Test que verifica la prioridad de LLMs."""
    
    print("=" * 80)
    print("TEST: Verificación de prioridad de LLMs")
    print("=" * 80)
    print()
    
    # Intentar inicializar TriageCrew
    print("🔧 Inicializando TriageCrew...")
    try:
        crew = TriageCrew()
        
        if crew.llm is None:
            print("❌ ERROR: No se pudo inicializar ningún LLM")
            return False
        
        # Detectar qué LLM se está usando
        llm_type = type(crew.llm).__name__
        llm_module = type(crew.llm).__module__
        
        print(f"✅ LLM inicializado exitosamente")
        print(f"   Tipo: {llm_type}")
        print(f"   Módulo: {llm_module}")
        print()
        
        # Verificar si es LM Studio (crewai.LLM con base_url de localhost)
        if llm_type == "LLM" and hasattr(crew.llm, 'base_url'):
            base_url = getattr(crew.llm, 'base_url', '')
            model = getattr(crew.llm, 'model', '')
            
            print(f"   Base URL: {base_url}")
            print(f"   Model: {model}")
            print()
            
            if 'localhost:1234' in base_url or '127.0.0.1:1234' in base_url:
                print("🎯 ✅ CORRECTO: Usando LM Studio local")
                print()
                print("💡 LM Studio detectado como LLM principal")
                print("   - No consumirá cuota de Gemini API")
                print("   - Respuestas más rápidas y privadas")
                print("   - Sin límites de rate limiting")
                return True
            else:
                print("⚠️ ADVERTENCIA: LLM configurado pero no apunta a LM Studio")
                print(f"   Base URL: {base_url}")
                return False
        
        # Verificar si es LMStudioLiteLLM (formato antiguo)
        elif 'lmstudio' in llm_module.lower() or 'LMStudioLiteLLM' in llm_type:
            print("🎯 ✅ CORRECTO: Usando LM Studio local")
            print()
            print("💡 LM Studio detectado como LLM principal")
            print("   - No consumirá cuota de Gemini API")
            print("   - Respuestas más rápidas y privadas")
            print("   - Sin límites de rate limiting")
            return True
        
        # Si no es LM Studio, verificar si es Gemini (fallback esperado)
        elif 'gemini' in llm_module.lower() or 'google' in llm_module.lower():
            print("⚠️ ADVERTENCIA: Usando Gemini API (fallback)")
            print()
            print("💡 Razones posibles:")
            print("   1. LM Studio no está ejecutándose")
            print("   2. No hay modelo cargado en LM Studio")
            print("   3. Puerto 1234 no responde")
            print()
            print("🔧 Para usar LM Studio:")
            print("   1. Abre LM Studio")
            print("   2. Carga un modelo (ej: qwen2.5-14b-instruct)")
            print("   3. Inicia el servidor local (puerto 1234)")
            print("   4. Reinicia el bot de Telegram")
            return False
        
        else:
            print(f"⚠️ LLM desconocido: {llm_type}")
            return False
            
    except Exception as exc:
        print(f"❌ ERROR al inicializar TriageCrew: {exc}")
        return False


if __name__ == "__main__":
    success = test_llm_priority()
    
    print()
    print("=" * 80)
    if success:
        print("✅ TEST PASSED: LM Studio configurado como prioridad")
    else:
        print("⚠️ TEST FAILED: Usando Gemini API (fallback)")
    print("=" * 80)
    
    sys.exit(0 if success else 1)
