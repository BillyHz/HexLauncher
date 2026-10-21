# Rendimiento de navegación — 21 de octubre de 2026

Pruebas locales en Windows 11, Python 3.14.6 y CustomTkinter 5.2.2, con una
ventana real visible de 1000 × 680 y datos temporales. Se usaron 20 tarjetas de
mods y 20 de texturas, así como una ráfaga de 40 actualizaciones de progreso.
Las respuestas de búsqueda fueron locales para aislar el coste de la interfaz.
No se ejecutaron Minecraft, Java ni Playit. Las cifras incluyen el coste de
cProfile y no representan un límite garantizado en todos los equipos.

## Comparación

| Medición | Antes | Después |
| --- | ---: | ---: |
| 60 cambios: mediana del manejador de navegación | 24,2 ms | 8,9 ms |
| 60 cambios: máximo del manejador de navegación | 360,1 ms | 12,0 ms |
| 60 cambios: máxima separación entre pulsos del bucle de interfaz | 424,1 ms | 47,6 ms |
| 60 cambios: tiempo de CPU del proceso | 3,77 s | 1,78 s |
| 300 cambios y dos búsquedas: mediana del manejador | 23,2 ms | 8,9 ms |
| 300 cambios y dos búsquedas: máxima separación entre pulsos | 896,7 ms | 296,8 ms |
| 300 cambios y dos búsquedas: tiempo de CPU | 16,41 s | 9,69 s |
| Tarjetas de mods conservadas al finalizar | 0 de 20 | 20 de 20 |

El manejador mide desde la activación del botón hasta que devuelve el control.
El pulso solicitado cada 10 ms detecta también trabajo de dibujo, disposición
y otros callbacks que pueden bloquear el bucle de eventos. Bajo búsquedas
simultáneas aún se observó un pico de unos 297 ms: la mejora no implica que
todas las operaciones gráficas duren menos de un fotograma.

En la prueba de 300 cambios corregida no hubo excepciones de Tk ni una sección
equivocada en la comprobación de la ventana superior. Los 10 hilos nativos del
proceso al inicio seguían siendo 10 al final, sin nuevos hilos Python vivos ni
procesos hijos. La memoria residente pasó de 76,7 a 78,8 MiB; este ensayo corto
no basta para descartar todas las posibles fugas a largo plazo.

La comprobación final de 60 cambios terminó con la cola de callbacks vacía y
un solo contenedor de resultados por sección. La suite completa pasó con
238 pruebas, incluidas las pruebas optativas del ejecutable e instalador reales.

## Trabajo que ejecutaba cada acción

- Cambiar de pestaña recorría los textos de todas las vistas, actualizaba los
  cinco botones y desmontaba su disposición. Volver a Mods destruía además
  los resultados. Ahora sólo se actualizan los dos botones afectados y se
  eleva la vista existente. No inicia peticiones, hilos ni procesos.
- Cada callback de un trabajador volvía a traducir toda la interfaz. Ahora
  los mensajes se traducen al asignarse y la cola cede el control tras unos
  8 ms de trabajo. El recorrido completo queda para inicio y cambio de idioma.
- Crear o borrar resultados hacía todo el trabajo de una vez. Ahora se
  procesa un máximo de dos tarjetas por tanda y se cancela el renderizado
  pendiente si cambia la búsqueda o su contexto.
- Las barras de desplazamiento de CustomTkinter forzaban un
  `update_idletasks()` desde su dibujo. El adaptador local agrupa sus valores
  y deja que el bucle normal pinte su canvas, evitando el repintado recursivo.
  Está cubierto por una prueba y debe revisarse al actualizar CustomTkinter.
- Las vistas se mantienen construidas, incluidos texto introducido y posición
  de desplazamiento. Cambiar de versión, cargador o instancia invalida los
  resultados correspondientes. El resumen de Inicio se actualiza por cambios
  de esos datos, ajustes e instalaciones.

## Reproducción

```powershell
python scripts/profile_navigation.py --output build/navigation-current
python scripts/profile_navigation.py --output build/navigation-stress --rounds 60 --stress
python -m pytest tests/test_navigation.py -q
```

El script genera JSON de tiempos, memoria, hilos, procesos hijos y errores,
además de un perfil de llamadas en TXT. Cierra la ventana al finalizar y no
modifica los datos de los jugadores. Las mediciones iniciales que no llegaron
a mostrar la ventana se descartaron de esta comparación.
