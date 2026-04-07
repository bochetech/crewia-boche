"""Test simple para verificar que el flujo básico de triage funciona."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.triage_crew import TriageCrew, TriageDecisionOutput

def test_simple():
    print("\n" + "="*80)
    print("TEST SIMPLE: Verificar flujo básico de triage")
    print("="*80)
    
    email = """De: test@test.com
Asunto: Sistema de gestión de mantenimiento

Implementar sistema de gestión de mantenimiento para limpieza de viña.
"""
    
    print("\n📨 INPUT:")
    print(email)
    
    print("\n🚀 Inicializando TriageCrew...")
    crew = TriageCrew()
    
    print("✅ LLM configurado:", type(crew.llm).__name__)
    print("✅ Config cargada: agents.yaml =", bool(crew._agents_cfg))
    print("✅ Config cargada: tasks.yaml =", bool(crew._tasks_cfg))
    
    print("\n⚙️ Ejecutando kickoff()...")
    
    try:
        result = crew.kickoff(email)
        
        print("\n" + "="*80)
        print("📊 RESULTADO")
        print("="*80)
        
        print(f"\n✓ Tipo: {type(result).__name__}")
        print(f"✓ Clasificación: {result.classification}")
        print(f"✓ Razonamiento: {result.reasoning[:200]}...")
        print(f"✓ Descartado: {result.discarded}")
        print(f"✓ Acciones ejecutadas: {len(result.actions_taken)}")
        
        for i, action in enumerate(result.actions_taken, 1):
            print(f"\n  Acción {i}:")
            print(f"    Tool: {action.tool}")
            print(f"    Status: {action.status}")
            print(f"    Details: {action.details[:100]}...")
        
        print("\n" + "="*80)
        print("✅ TEST COMPLETADO")
        print("="*80)
        
        return result
        
    except Exception as exc:
        print(f"\n❌ ERROR: {exc}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    # Verificar API key
    if not os.getenv("GEMINI_API_KEY"):
        print("\n⚠️ WARNING: GEMINI_API_KEY no configurada")
        print("   Ejecuta: export GEMINI_API_KEY=your_key\n")
        sys.exit(1)
    
    result = test_simple()
    
    if result:
        print("\n✅ Test exitoso")
    else:
        print("\n❌ Test fallido")
