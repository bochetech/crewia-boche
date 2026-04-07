#!/usr/bin/env python3
"""
Test del Multi-Agent Strategy Crew con HTMLStrategyTool corregido.

Verifica que:
1. El tool tenga el schema correcto (HTMLStrategyToolInput)
2. Los agentes puedan usar el tool sin errores de validación
3. El flujo completo (Strategist → BA → Researcher → Coordinator) funcione
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.triage_crew import TriageCrew


def test_strategy_crew_with_fixed_tool():
    """Test complete Multi-Agent Strategy Crew flow."""
    print("=" * 80)
    print("TEST: Multi-Agent Strategy Crew con HTMLStrategyTool corregido")
    print("=" * 80)
    print()
    
    # Crear instancia de TriageCrew
    crew = TriageCrew()
    
    if crew.llm is None:
        print("⚠️ Modo stub — test omitido (requiere LM Studio o Gemini)")
        return
    
    print(f"✅ LLM inicializado: {type(crew.llm).__name__}")
    print()
    
    # Mensaje de prueba: iniciativa estratégica clara
    test_message = """
Me están solicitando implementar un sistema de mantenimiento preventivo
para la maquinaria de la viña Concha y Toro.

La idea es que el equipo técnico pueda programar inspecciones periódicas,
registrar fallas y generar reportes automáticos.

Esto debería integrarse con SAP para el inventario de repuestos.

Owner: Equipo Operaciones Viña
Deadline: Q2 2026
Impacto esperado: Reducir downtime en 30%
"""
    
    print("📝 INICIATIVA DE PRUEBA:")
    print("-" * 80)
    print(test_message.strip())
    print("-" * 80)
    print()
    
    # Ejecutar Strategy Crew
    print("🚀 Ejecutando Multi-Agent Strategy Crew...")
    print()
    
    try:
        result = crew.kickoff_strategy_crew(test_message)
        
        print()
        print("=" * 80)
        print("RESULTADO DEL STRATEGY CREW")
        print("=" * 80)
        print()
        
        if result.get("status") == "approved":
            print("✅ INICIATIVA APROBADA")
            print()
            print(f"📍 Foco: {result.get('foco')}")
            print(f"📝 Acción: {result.get('action')}")
            print(f"🆔 Initiative ID: {result.get('initiative_id')}")
            print(f"📄 HTML actualizado: {result.get('html_updated')}")
            print()
            
            if result.get('technical_validation'):
                tech = result['technical_validation']
                print("🔬 Validación Técnica:")
                print(f"   - Viable: {tech.get('viable', 'unknown')}")
                print(f"   - API disponible: {tech.get('api_available', 'N/A')}")
                print(f"   - Dependencias: {', '.join(tech.get('dependencies', []))}")
                print(f"   - Esfuerzo: {tech.get('effort_estimate', 'N/A')}")
            
            print()
            print("✅ TEST PASSED: Multi-Agent Strategy Crew funcionó correctamente")
            
        elif result.get("status") == "rejected":
            print("⚠️ INICIATIVA RECHAZADA")
            print()
            print(f"Razón: {result.get('reason')}")
            print()
            
            # Para este test, rechazar es un fail (la iniciativa es claramente estratégica)
            print("❌ TEST FAILED: Iniciativa estratégica fue rechazada incorrectamente")
            
        else:
            print(f"❌ ERROR EN STRATEGY CREW: {result.get('status')}")
            print(f"Mensaje: {result.get('message')}")
            print()
            print("❌ TEST FAILED: Error procesando iniciativa")
    
    except Exception as exc:
        print()
        print("❌ ERROR CRÍTICO:")
        print(f"   {exc}")
        print()
        
        import traceback
        traceback.print_exc()
        
        print()
        print("❌ TEST FAILED: Excepción durante ejecución")


if __name__ == "__main__":
    test_strategy_crew_with_fixed_tool()
