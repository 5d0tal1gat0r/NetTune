Esta es una ficha diaria interna de un centro comercial, rellenada a mano
por su personal. El propietario del documento solicita su transcripción para
archivarla.

Hay DOS tipos de ficha. Identifica primero cuál es y usa SOLO el vocabulario de
ese tipo; no mezcles los dos.

===== TIPO "mantenimiento" =====
Título habitual: "FICHA DIARIA DE TRABAJO DE MANTENIMIENTO".
DE DONDE SACAR "trabajos": EXCLUSIVAMENTE de la tabla "DESCRIPCION DE LOS
TRABAJOS", que tiene columna "Hora". La rellena el equipo de mantenimiento.
No transcribas como anotaciones la cabecera (FECHA, HORA ENTRADA, HORA SALIDA,
OPERARIOS, las casillas TRABAJO DIURNO/NOCTURNO/FESTIVO) ni el pie. De la
cabecera usa solo la fecha y los operarios, en sus propios campos.
  Acciones: revisando, revisión, conectando, comprobando, reparando, limpiando,
    pintando, desatoro, instalación, funcionamiento, prueba sin carga.
  Elementos: cuadros eléctricos, mq (máquinas) de aire, mq de cobre, grupo
    electrógeno, transformador, cargadores (puntos de recarga de coches), aire
    acondicionado, fachada, telefonía, fosa séptica, sumidero, escalera
    mecánica, alumbrado, acometida, muelle, puerta de emergencia, manivela,
    cuarto de aseos, urinario, fluxómetro (de wáter), tubería, contador,
    compactador o compactadora, gotera, fuga, riego, extintores.
  Empresas y proveedores que aparecen a menudo: Endesa (electricidad),
    ATIS (contra incendios y camaras), Schindler (ascensores, rampas y
    escaleras mecanicas), Telefónica (telefonia y datos), Aguasur (agua),
    Saneasur, Carrefour, Digi. A veces las escriben en MAYÚSCULAS. Son nombres
    de empresa, no de persona: transcribelos tal cual y NO los sustituyas ni
    los elimines.
  Ubicaciones: parking exterior, planta cero, planta alta; plantas escritas
    P/C (planta calle), P/A (planta alta) y P/0 (planta baja); las plantas
    del parking P-1 y P-2; zonas Z0, Z1, Z2... como en las fichas de
    seguridad; plazas y puertas escritas como 2-6, 7-6, 7-4, 7-9, L-32;
    abreviaturas PC, PK, PQ, PØ.
  Tiempo: los trabajos de parking suelen llevar el tiempo que costaron,
    como (2H) o (1H). Transcríbelo tal cual.
  MARCA DE PARKING: si junto a una anotación hay un círculo con una X dentro,
    o la anotación está escrita o marcada en rojo, añade al final de esa
    anotación, separado por un espacio, exactamente: [parking]
    No lo añadas en ningún otro caso.

===== TIPO "seguridad" =====
Hoja "INFORME DIARIO" de la empresa SECUPOL para el C.C. NETTUNE.

DE DONDE SACAR "trabajos": EXCLUSIVAMENTE del recuadro titulado
"Orden cronologico de Acontecimientos - Incidentes - Alarmas", que tiene una
columna "Hora" y una columna de descripcion. Cada renglon escrito de ese
recuadro es una anotacion. Nada mas de la hoja entra en "trabajos".

NO transcribas como anotaciones, aunque haya texto escrito a mano:
  - la cabecera: Fecha, Servicio, Direccion, Horario, Puesto, y el recuadro
    "Vigilantes de servicio" con D./Dña. y sus nombres;
  - el pie: "Firma de los vigilantes", con sus columnas Horario, "Nombre y
    Apellidos y TIP" y las firmas;
  - cabeceras de columna, logotipos, ni el propio titulo del recuadro.
De la cabecera usa solo la fecha (campo "fecha"), la hora de INICIO del
"Horario: de ... a ..." (campo "horario") y los nombres de los vigilantes
(campo "operarios"). Esos NO se repiten dentro de "trabajos".

Una hoja escaneada puede contener DOS turnos seguidos (por ejemplo 07:00-15:00
y 15:00-23:00), cada uno con su propio recuadro: transcribe los dos recuadros,
en orden.
Suele empezar por "Comienzo el servicio" o "Inicio servicio" y terminar por
"Finalizo servicio" o "Finaliza el servicio".
Muchas anotaciones van EN MAYUSCULAS; transcribelas tal cual.
  Acciones: inicio/finalización del servicio, apertura, cierre, se abre, se
    cierra, se colocan, se quitan, se retiran, se revisan, rondas, se llama la
    atención, se recibe queja, salida de empleados, incorporación de personal.
  Empresas y proveedores que aparecen a menudo: Endesa (electricidad),
    ATIS (contra incendios y camaras), Schindler (ascensores, rampas y
    escaleras mecanicas), Telefonica (telefonia y datos). Son nombres de
    empresa, no de persona: transcribelos tal cual.
  Elementos: pilonas (OJO: "pilonas", nunca "peliculas", "pelonas" ni
    "pilones"), torreones (nunca "torretas", "tornos" ni "torniquetes"),
    portón, rampas,
    accesos, puertas principales, terraza, muelle, alumbrado (de tarde, de
    noche, exterior), ascensor, aseos, sistemas de seguridad, contenedor,
    albarán, patinete, moto.
  Ubicaciones: zonas escritas con Z y número: Z1, Z2, Z3, Z4, Z6-1, Z7, Z9,
    Z10, Z12, Z27; "zona 1, 2, 3"; plantas: planta cero, planta baja, P0, PA,
    PC; también "B 1/3".
  Frases habituales: "Se retiran pilonas", "Se colocan pilonas Z3 y Z1",
    "Se abren torreones", "Se cierran torreones Z2 y Z3", "Se abre zona 1, 2, 3",
    "Se abre planta cero", "Se conectan rampas", "Se abren terrazas",
    "Se abre muelle", "Se cierra muelle", "Se conecta alumbrado de tarde",
    "Se realizan rondas", "Relevo VS", "Se llama la atencion a ...".

===== REGLAS COMUNES =====
Estas fichas son recientes: de {AÑO}, o de {AÑO_ANTERIOR} si son de sus últimos
meses. Un año que parezca {AÑO_DIEZ_ANTES} u otro lejano es casi con seguridad
{AÑO} o {AÑO_ANTERIOR}; aun así lee los dígitos uno a uno.

Distingue con cuidado palabras parecidas en cursiva:
  "aire" lleva punto sobre la i y no tiene astas altas;
  "cobre" tiene el asta alta de la b.

Devuelve SOLO un objeto JSON, sin texto alrededor y sin ```:
{
  "tipo":      "mantenimiento" o "seguridad" (o null si no lo tienes claro),
  "titulo":    el título impreso del documento, tal cual aparece,
  "fecha":     la fecha de la ficha en formato DD-MM-YYYY, o null,
  "horario":   la hora de inicio del turno, la primera hora de "Horario: de
               ... a ...", en formato HH:MM (por ejemplo "07:00"), o null,
  "operarios": lista de nombres que aparecen como operarios o vigilantes,
  "trabajos":  lista de las anotaciones de la tabla, una entrada por frase
               completa (si una frase ocupa dos líneas, únelas)
}
Transcribe en español, literalmente. Marca con [?] cualquier palabra que no
leas con seguridad. Si un campo no aparece, usa null o una lista vacía.

REGLA MÁS IMPORTANTE: NO INVENTES NADA.
  - Transcribe únicamente lo que está escrito en la imagen. No añadas
    anotaciones que no veas, por muy habituales que sean en estas fichas.
  - Si una línea no se lee, escríbela con [?] en las palabras dudosas. Si no se
    lee nada de ella, omítela por completo.
  - Si hay un bloque de varias líneas seguidas escritas que no se leen, no lo
    trocees en fragmentos con [?] ni lo omitas: escribe en su lugar una sola
    anotación, exactamente "[?] (grupo de texto ilegible)". Alguien lo leerá
    luego sobre el papel.
  - Es MUCHO mejor devolver menos anotaciones que inventar una. Una lista corta
    y fiel es correcta; una lista completa con frases inventadas no lo es.
  - No completes una frase a medias con lo que "tendría sentido". Déjala como
    esté, con [?].
  - No uses el vocabulario de arriba para rellenar huecos: sirve para decidir
    entre dos lecturas posibles de algo que SÍ está escrito, no para suponer
    qué pone donde no lo distingues.
  - Si la hoja está en blanco o ilegible, devuelve "trabajos": [].
