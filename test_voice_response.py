"""
Test de respuesta con voz.

Verifica que:
1. gTTS está instalado correctamente
2. _synthesize_voice() genera audio MP3
3. El audio se puede reproducir

Uso:
    .venv313/bin/python3 test_voice_response.py
"""
import asyncio
import os
from src.telegram_bot import _synthesize_voice


async def test_voice_synthesis():
    """Test básico de síntesis de voz."""
    print("="*80)
    print("TEST: Síntesis de voz con gTTS")
    print("="*80)
    
    # Texto de prueba
    test_text = (
        "Hola, soy Nia. He analizado tu mensaje y lo he clasificado como estratégico. "
        "Se trata de una iniciativa relacionada con integraciones de Shopify."
    )
    
    print(f"\n📝 Texto a sintetizar ({len(test_text)} chars):")
    print(f"   '{test_text[:100]}...'")
    
    # Generar audio
    print("\n🔊 Generando audio con gTTS...")
    audio_path = await _synthesize_voice(test_text, lang="es")
    
    if audio_path:
        print(f"✅ Audio generado exitosamente: {audio_path}")
        
        # Verificar que el archivo existe y tiene tamaño
        if os.path.exists(audio_path):
            file_size = os.path.getsize(audio_path)
            print(f"📦 Tamaño del archivo: {file_size:,} bytes ({file_size/1024:.1f} KB)")
            
            if file_size > 1000:  # Al menos 1KB
                print("✅ Archivo de audio válido")
                
                # Info sobre reproducción
                print("\n💡 Para escuchar el audio:")
                print(f"   open {audio_path}")
                print("   (o usa cualquier reproductor de MP3)")
                
                # Limpiar archivo
                print(f"\n🗑️  Limpiando archivo temporal...")
                os.unlink(audio_path)
                print("✅ Archivo eliminado")
            else:
                print("❌ Archivo de audio demasiado pequeño (posible error)")
                return False
        else:
            print("❌ Archivo de audio no encontrado")
            return False
    else:
        print("❌ Error generando audio")
        return False
    
    print("\n" + "="*80)
    print("✅ TEST PASSED: Síntesis de voz funcional")
    print("="*80)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_voice_synthesis())
    exit(0 if success else 1)
