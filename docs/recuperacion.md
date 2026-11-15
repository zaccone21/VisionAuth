# Recuperación

## No me reconoce

- Entrá con el PIN: en la pantalla de inicio, "Opciones de inicio de sesión".
- Desde el menú (`.\visionauth.ps1`), "Probar reconocimiento" muestra con qué
  similitud te ve. Si queda cerca del umbral, "Sumar muestras a una cara"
  desde donde desbloqueás suele alcanzar.
- Revisá el log (opción 13) por errores de cámara.

## La isla dice "Entrá con tu PIN"

La contraseña guardada no funcionó, casi siempre porque cambiaste la
contraseña de tu cuenta. Entrá con el PIN y guardá la nueva desde el menú
(opción 6).

## La isla dice "VisionAuth no está activo"

El servicio no responde. Entrá con el PIN y fijate el estado en el menú: si
está en pausa, reanudalo; si no, revisá el log.

## La pantalla de inicio no funciona

Si la pantalla de inicio no responde o se cierra:

1. Probá primero con el PIN, en "Opciones de inicio de sesión".
2. Si aún así no podés entrar, en la pantalla de inicio mantené **Shift** y
   elegí **Reiniciar** (desde el botón de apagado). Windows abre el entorno
   de recuperación.
3. Andá a **Solucionar problemas > Opciones avanzadas > Símbolo del
   sistema**.
4. Borrá la DLL. En este modo la letra de la unidad de Windows puede no ser
   `C:`; probá con `dir C:\`, `dir D:\` hasta encontrar la carpeta `Windows`:
   ```
   del "C:\Program Files\VisionAuth\VisionAuthCredentialProvider.dll"
   ```
5. Reiniciá. Sin la DLL, Windows ignora el componente de VisionAuth y la
   pantalla de inicio vuelve a la normalidad.

Después, desinstalá VisionAuth como se explica abajo.

## Desinstalar

En PowerShell como administrador, desde la carpeta de VisionAuth:

```powershell
.\scripts\uninstall.ps1
```

Quita el servicio, el componente de la pantalla de inicio, la contraseña
guardada, los ajustes del registro y la política de la pantalla del reloj.
No borra las caras registradas (`data\users\`) ni el log
(`C:\ProgramData\VisionAuth\`): borralos a mano si no los querés.

Si la desinstalación dice que la DLL está en uso, ya quedó desregistrada:
borrá `C:\Program Files\VisionAuth` después de reiniciar.
