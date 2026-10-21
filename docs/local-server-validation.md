# Prueba real de servidor local y Playit — 21 de octubre de 2026

Se ejecutó Paper 1.21.11 build 132 con Java 21 y 2 GiB de RAM, junto al agente
oficial Playit 0.17.1. La prueba utilizó una carpeta independiente bajo `build/`
y un mundo nuevo. No se modificó el mundo habitual de `HexServer`.

El túnel existente estaba desactivado por el usuario. Con su autorización
expresa se habilitó desde el panel de Playit durante la prueba y se volvió a
desactivar al terminar. La clave del agente permite consultar los túneles,
pero no autorizó cambiar ese ajuste; no se modificaron credenciales.

## Resultados

| Comprobación | Primer arranque | Segundo arranque |
| --- | --- | --- |
| Servidor listo | Sí | Sí |
| Respuesta Minecraft en `127.0.0.1:25565` | Paper 1.21.11 | Paper 1.21.11 |
| Respuesta por `rails-slips.tun.ply.gg` | Paper 1.21.11 | Paper 1.21.11 |
| Intercambio público de estado y ping, tiempo total | 2121,0 ms | 624,7 ms |
| Mundo guardado al detener | Sí | Sí |
| Identidad del mundo conservada | Sí | Sí |
| Procesos Java y Playit finalizados | Sí | Sí |
| Errores de ciclo de vida tras las correcciones | Ninguno | Ninguno |

Se intercambiaron paquetes reales del protocolo Minecraft Java: handshake,
consulta JSON de estado y ping/pong con validación del contenido recibido.
Las conexiones públicas atravesaron Playit desde este equipo; no se simuló
el transporte ni la respuesta. No se probó una sesión de juego con un jugador
remoto ni se midieron TPS bajo carga. Los tiempos anteriores incluyen DNS,
conexión y ambos intercambios; no son una medición aislada de latencia de juego.

Playit intentó IPv6, que no estaba disponible, y conectó por IPv4. Esa advertencia
no impidió el funcionamiento del túnel. El código de salida 1 del agente al
detenerlo corresponde a la terminación solicitada por el administrador del
launcher; Java terminó con código 0 tras guardar el mundo.

## Fallos encontrados y corregidos

1. El monitor de salida podía terminar después de que `stop_server()` restableciera
   su bandera de cierre, produciendo una alerta falsa de salida inesperada con
   código 0. Ahora se invalida la generación finalizada bajo el mismo bloqueo.
   Las pruebas reproducen la llegada tardía de ambos monitores.
2. En el modo `--stdout`, el agente 0.17.1 sólo registra la primera línea de su
   pantalla; omite las líneas donde figuraban las direcciones. El launcher ahora
   consulta el endpoint de lectura del propio agente y selecciona únicamente
   túneles TCP habilitados dirigidos a loopback y puerto 25565. También informa
   cuando ese túnel está desactivado. Las consultas se limitan a una por 15 s,
   se hacen en el trabajador y se descartan si el servidor ya se detuvo.

Referencias del agente oficial: [salida de consola](https://github.com/playit-cloud/playit-agent/blob/v0.17.1/packages/agent_cli/src/ui/mod.rs),
[consulta de los túneles](https://github.com/playit-cloud/playit-agent/blob/v0.17.1/packages/agent_cli/src/autorun.rs),
[cliente de la API](https://github.com/playit-cloud/playit-agent/blob/v0.17.1/packages/api_client/src/api.rs).

## Repetir la prueba

```powershell
python -m pytest tests/test_playit.py tests/test_server_manager.py tests/test_server_view.py tests/test_server_loaders.py -q
python scripts/test_live_server.py --require-public
```

El ensayo real requiere una instalación existente en `HexServer`, Java en
`HexJDK`, puerto 25565 libre y un túnel configurado y habilitado para ese agente.
El script no crea ni habilita túneles. Si se habilita uno temporalmente, hay
que restaurar su estado desde el panel al terminar. Genera un reporte en
`build/server-live-report.json`, conserva los logs de prueba y elimina la copia
temporal de la clave. `--require-public` devuelve error si cualquiera de los
dos ciclos no recibe una respuesta pública de Minecraft.
