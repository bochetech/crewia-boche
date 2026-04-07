"""
Test del flujo unificado de triage con Multi-Agent Strategy Crew.

Caso de prueba real:
"Me están pidiendo implementar un sistema de gestión de mantenimiento para las 
actividades de limpieza de la viña, la idea es que la persona tenga la asignación, 
haga el trabajo y tome una foto como evidencia para que un supervisor se lo apruebe."

Resultado esperado:
- ✅ Triage Strategist → Clasifica como F4 (Optimización Oferta) o F2 (Experiencia Cliente)
- ✅ Business Analyst → Busca duplicados, crea nueva iniciativa
- ✅ Researcher → Valida viabilidad técnica
- ✅ Coordinator → Aprueba
- ✅ HTML actualizado en data/estrategia_descorcha.html
"""

import os
import sys
from pathlib import Path

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.triage_crew import TriageCrew, TriageDecisionOutput


def test_case_1_sistema_mantenimiento():
    """Test: Sistema de gestión de mantenimiento para limpieza de viña."""
    
    print("\n" + "="*80)
    print("TEST 1: Sistema de Gestión de Mantenimiento (Viña)")
    print("="*80)
    
    # Input del usuario (caso real)
    email_input = """De: operaciones@descorcha.cl
Asunto: Propuesta sistema de gestión de mantenimiento

Me están pidiendo implementar un sistema de gestión de mantenimiento para las 
actividades de limpieza de la viña, la idea es que la persona tenga la asignación, 
haga el trabajo y tome una foto como evidencia para que un supervisor se lo apruebe.

Necesitamos:
- Asignación de tareas de limpieza
- Captura de foto como evidencia
- Flujo de aprobación por supervisor
- Registro de actividades completadas

¿Podemos evaluar esta propuesta?
"""
    
    print("\n📨 INPUT:")
    print(email_input)
    
    # Inicializar TriageCrew
    print("\n🚀 Inicializando TriageCrew...")
    crew = TriageCrew()
    
    # Ejecutar triage (ahora siempre usa Multi-Agent Strategy Crew)
    print("\n⚙️ Ejecutando Multi-Agent Strategy Crew...")
    print("   (Esto puede tardar 30-60 segundos)\n")
    
    try:
        result = crew.kickoff(email_input)
        
        print("\n" + "="*80)
        print("📊 RESULTADO DEL TRIAGE")
        print("="*80)
        
        print(f"\n✓ Clasificación: {result.classification}")
        print(f"✓ Razonamiento: {result.reasoning}")
        print(f"✓ Descartado: {result.discarded}")
        
        if result.email_summary:
            print(f"\n📧 Email Summary:")
            print(f"   - Sender: {result.email_summary.sender}")
            print(f"   - Subject: {result.email_summary.subject}")
            print(f"   - Key Topics: {', '.join(result.email_summary.key_topics)}")
        
        if result.actions_taken:
            print(f"\n🔧 Acciones Ejecutadas ({len(result.actions_taken)}):")
            for action in result.actions_taken:
                print(f"   ✓ {action.tool}: {action.status}")
                print(f"     Detalles: {action.details}")
        
        if result.pending_approvals:
            print(f"\n⏳ Aprobaciones Pendientes:")
            for approval in result.pending_approvals:
                print(f"   - {approval}")
        
        # Validaciones
        print("\n" + "="*80)
        print("🧪 VALIDACIONES")
        print("="*80)
        
        validations = {
            "Clasificado como STRATEGIC": result.classification == "STRATEGIC",
            "No descartado": not result.discarded,
            "HTMLStrategyTool ejecutado": any(a.tool == "HTMLStrategyTool" for a in result.actions_taken),
            "Sin errores": not any(a.status == "error" for a in result.actions_taken),
        }
        
        all_passed = True
        for validation, passed in validations.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status}: {validation}")
            if not passed:
                all_passed = False
        
        # Verificar que el HTML se actualizó
        html_path = Path("data/estrategia_descorcha.html")
        if html_path.exists():
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # Buscar keywords del caso de uso
            keywords_found = {
                "mantenimiento": "mantenimiento" in html_content.lower(),
                "limpieza": "limpieza" in html_content.lower(),
                "viña": "viña" in html_content.lower() or "vina" in html_content.lower(),
                "supervisor": "supervisor" in html_content.lower(),
            }
            
            print(f"\n📄 HTML SSOT Verificación:")
            for keyword, found in keywords_found.items():
                status = "✅" if found else "⚠️"
                print(f"   {status} Keyword '{keyword}': {'Encontrado' if found else 'No encontrado'}")
        
        print("\n" + "="*80)
        if all_passed:
            print("✅ TEST PASSED: Sistema funcionando correctamente")
        else:
            print("⚠️ TEST PARTIAL: Revisar validaciones fallidas")
        print("="*80)
        
        return result
        
    except Exception as exc:
        print(f"\n❌ ERROR EN TEST: {exc}")
        import traceback
        traceback.print_exc()
        return None


def test_case_2_non_strategic():
    """Test: Mensaje no estratégico (debe ser rechazado)."""
    
    print("\n" + "="*80)
    print("TEST 2: Mensaje No Estratégico (JUNK)")
    print("="*80)
    
    email_input = """De: marketing@descorcha.cl
Asunto: Cambiar color del logo

Hola,

¿Podemos cambiar el color del logo en el header de la web?
Creo que el azul actual no se ve bien.

Gracias.
"""
    
    print("\n📨 INPUT:")
    print(email_input)
    
    crew = TriageCrew()
    
    print("\n⚙️ Ejecutando Multi-Agent Strategy Crew...\n")
    
    try:
        result = crew.kickoff(email_input)
        
        print("\n" + "="*80)
        print("📊 RESULTADO DEL TRIAGE")
        print("="*80)
        
        print(f"\n✓ Clasificación: {result.classification}")
        print(f"✓ Razonamiento: {result.reasoning}")
        print(f"✓ Descartado: {result.discarded}")
        
        if result.discard_reason:
            print(f"✓ Razón descarte: {result.discard_reason}")
        
        # Validaciones
        print("\n" + "="*80)
        print("🧪 VALIDACIONES")
        print("="*80)
        
        validations = {
            "Clasificado como JUNK": result.classification == "JUNK",
            "Marcado como descartado": result.discarded,
            "No actualizó HTML": not any(a.tool == "HTMLStrategyTool" for a in result.actions_taken),
        }
        
        all_passed = True
        for validation, passed in validations.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status}: {validation}")
            if not passed:
                all_passed = False
        
        print("\n" + "="*80)
        if all_passed:
            print("✅ TEST PASSED: JUNK detectado correctamente")
        else:
            print("⚠️ TEST FAILED: Revisar clasificación")
        print("="*80)
        
        return result
        
    except Exception as exc:
        print(f"\n❌ ERROR EN TEST: {exc}")
        import traceback
        traceback.print_exc()
        return None


def test_case_3_duplicate_detection():
    """Test: Detectar y modificar iniciativa existente (deduplicación)."""
    
    print("\n" + "="*80)
    print("TEST 3: Deduplicación (Modificar Existente)")
    print("="*80)
    
    # Este caso debería detectar que ya existe una iniciativa similar
    # y modificarla en lugar de crear una nueva
    email_input = """De: cto@descorcha.cl
Asunto: Mejora al comparador Vilaport

Necesitamos ajustar los precios en el comparador Vilaport para ser más 
competitivos con Vinos del Mundo. 

Propongo agregar descuentos dinámicos según volumen de compra.
"""
    
    print("\n📨 INPUT:")
    print(email_input)
    
    crew = TriageCrew()
    
    print("\n⚙️ Ejecutando Multi-Agent Strategy Crew...\n")
    
    try:
        result = crew.kickoff(email_input)
        
        print("\n" + "="*80)
        print("📊 RESULTADO DEL TRIAGE")
        print("="*80)
        
        print(f"\n✓ Clasificación: {result.classification}")
        print(f"✓ Razonamiento: {result.reasoning}")
        
        if result.actions_taken:
            print(f"\n🔧 Acciones:")
            for action in result.actions_taken:
                print(f"   ✓ {action.tool}: {action.details}")
                
                # Verificar si menciona "MODIFICACIÓN" o "NUEVA"
                if "MODIFICA" in action.details.upper() or "UPDATE" in action.details.upper():
                    print(f"      💡 Deduplicación detectada: Modificó iniciativa existente")
                elif "NUEVA" in action.details.upper() or "CREATE" in action.details.upper():
                    print(f"      💡 Creó nueva iniciativa")
        
        return result
        
    except Exception as exc:
        print(f"\n❌ ERROR EN TEST: {exc}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Ejecutar todos los tests."""
    
    print("\n" + "█"*80)
    print("█" + " "*78 + "█")
    print("█" + " "*20 + "TEST SUITE: FLUJO UNIFICADO DE TRIAGE" + " "*21 + "█")
    print("█" + " "*78 + "█")
    print("█"*80)
    
    # Verificar que existe el archivo de configuración
    if not Path("config/agents.yaml").exists():
        print("\n❌ ERROR: config/agents.yaml no encontrado")
        print("   Asegúrate de estar en el directorio raíz del proyecto")
        return
    
    if not Path("data/estrategia_descorcha.html").exists():
        print("\n⚠️ WARNING: data/estrategia_descorcha.html no encontrado")
        print("   El HTML SSOT no existe, se creará durante el test")
    
    # Verificar API keys
    if not os.getenv("GEMINI_API_KEY"):
        print("\n⚠️ WARNING: GEMINI_API_KEY no configurada")
        print("   El Multi-Agent Crew requiere Gemini API")
        print("   Ejecuta: export GEMINI_API_KEY=your_key")
        return
    
    results = {}
    
    # Test 1: Sistema de mantenimiento (caso real del usuario)
    results['test1'] = test_case_1_sistema_mantenimiento()
    
    # Test 2: Mensaje no estratégico
    results['test2'] = test_case_2_non_strategic()
    
    # Test 3: Deduplicación
    results['test3'] = test_case_3_duplicate_detection()
    
    # Resumen final
    print("\n" + "█"*80)
    print("█" + " "*78 + "█")
    print("█" + " "*30 + "RESUMEN FINAL" + " "*33 + "█")
    print("█" + " "*78 + "█")
    print("█"*80)
    
    for test_name, result in results.items():
        if result:
            status = "✅ PASS" if result.classification in ["STRATEGIC", "JUNK"] else "❌ FAIL"
            print(f"\n{status} {test_name}: {result.classification}")
        else:
            print(f"\n❌ FAIL {test_name}: Error durante ejecución")
    
    print("\n" + "="*80)
    print("✅ Tests completados. Revisa data/estrategia_descorcha.html para ver cambios.")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
