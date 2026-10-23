-- Familias que Suman | Esquema v2 | PostgreSQL 16+
-- Ejecutar UNA VEZ dentro de una base vacía. No elimina datos existentes.
-- El rol que lo ejecute debe poder crear schemas. No requiere extensiones.
-- Orden de ejecución 01_esquema.sql, 02_catalogos.sql, 03_roles.sql
BEGIN;
CREATE SCHEMA fqs;
SET LOCAL search_path = fqs, pg_catalog;

-- ============================================================
-- Catálogos
-- ============================================================

CREATE TABLE ciudades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    estado text NOT NULL CHECK (btrim(estado) <> ''),
    pais text NOT NULL DEFAULT 'México',
    zona_horaria text NOT NULL DEFAULT 'America/Monterrey',
    UNIQUE (nombre, estado, pais),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- clave es estable y la app la usa para elegir ícono y color (MEDIO_AMBIENTE, NINOS...)
CREATE TABLE categorias (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clave text NOT NULL CHECK (clave ~ '^[A-Z][A-Z_]*$'),
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    descripcion text,
    activa boolean NOT NULL DEFAULT true,
    UNIQUE (clave),
    UNIQUE (nombre),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- Usuarios y comunidad
-- ============================================================

-- El registro acepta correo o teléfono, al menos uno.
-- fecha_nacimiento es obligatoria para que el titular asista a una actividad.
CREATE TABLE usuarios (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    username text NOT NULL CHECK (btrim(username) <> '' AND username = btrim(username)),
    correo text CHECK (correo IS NULL OR (btrim(correo) <> '' AND correo = btrim(correo))),
    telefono text CHECK (telefono IS NULL OR telefono ~ '^[+]?[0-9]{10,15}$'),
    password_hash text NOT NULL CHECK (btrim(password_hash) <> ''),
    rol text NOT NULL DEFAULT 'familia' CHECK (rol IN ('familia','admin')),
    tipo_cuenta text NOT NULL DEFAULT 'familiar' CHECK (tipo_cuenta IN ('familiar','individual')),
    fecha_nacimiento date,
    ciudad_id uuid REFERENCES ciudades(id) ON DELETE RESTRICT,
    foto_clave text,
    estado text NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo','suspendido','pendiente_eliminacion','eliminado')),
    CONSTRAINT usuarios_requiere_contacto CHECK (estado = 'eliminado' OR num_nonnulls(correo, telefono) >= 1),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX usuarios_correo_uq ON usuarios(lower(correo));
CREATE UNIQUE INDEX usuarios_username_uq ON usuarios(lower(username));
CREATE UNIQUE INDEX usuarios_telefono_uq ON usuarios(telefono);

CREATE TABLE miembros_comunidad (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    relacion text NOT NULL CHECK (btrim(relacion) <> ''),
    fecha_nacimiento date NOT NULL,
    correo text,
    telefono text CHECK (telefono IS NULL OR telefono ~ '^[+]?[0-9]{10,15}$'),
    activo boolean NOT NULL DEFAULT true,
    UNIQUE (id, usuario_id),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE usuario_categorias (
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    categoria_id uuid NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT,
    PRIMARY KEY (usuario_id, categoria_id)
);

CREATE TABLE usuario_preferencias (
    usuario_id uuid PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    quiere_donar boolean NOT NULL DEFAULT false,
    quiere_participar boolean NOT NULL DEFAULT false,
    quiere_proponer boolean NOT NULL DEFAULT false,
    recibir_recordatorios boolean NOT NULL DEFAULT true,
    recibir_sugerencias boolean NOT NULL DEFAULT true,
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- Tokens FCM para recordatorios y notificaciones push
CREATE TABLE dispositivos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    token_fcm text NOT NULL CHECK (btrim(token_fcm) <> ''),
    plataforma text NOT NULL DEFAULT 'android' CHECK (plataforma IN ('android')),
    ultima_conexion timestamptz NOT NULL DEFAULT now(),
    UNIQUE (token_fcm),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- Recuperación de contraseña. Solo se guarda el hash del token, nunca el token.
CREATE TABLE tokens_recuperacion (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    token_hash text NOT NULL CHECK (btrim(token_hash) <> ''),
    expira_en timestamptz NOT NULL,
    usado_en timestamptz,
    UNIQUE (token_hash),
    CHECK (expira_en > creado_en),
    creado_en timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- Asociaciones y actividades
-- ============================================================

CREATE TABLE asociaciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    descripcion text NOT NULL CHECK (btrim(descripcion) <> ''),
    mision text,
    necesidades text,
    familias_beneficiadas integer NOT NULL DEFAULT 0 CHECK (familias_beneficiadas >= 0),
    categoria_id uuid NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT,
    ciudad_id uuid NOT NULL REFERENCES ciudades(id) ON DELETE RESTRICT,
    direccion text NOT NULL CHECK (btrim(direccion) <> ''),
    latitud numeric(9,6) CHECK (latitud BETWEEN -90 AND 90),
    longitud numeric(9,6) CHECK (longitud BETWEEN -180 AND 180),
    CHECK ((latitud IS NULL) = (longitud IS NULL)),
    telefono text,
    whatsapp text,
    correo text,
    sitio_web text,
    foto_clave text,
    verificada boolean NOT NULL DEFAULT false,
    activa boolean NOT NULL DEFAULT true,
    creado_por uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE actividades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    asociacion_id uuid NOT NULL REFERENCES asociaciones(id) ON DELETE RESTRICT,
    categoria_id uuid NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT,
    ciudad_id uuid NOT NULL REFERENCES ciudades(id) ON DELETE RESTRICT,
    titulo text NOT NULL CHECK (btrim(titulo) <> ''),
    descripcion_corta text NOT NULL CHECK (btrim(descripcion_corta) <> ''),
    descripcion text NOT NULL CHECK (btrim(descripcion) <> ''),
    recomendaciones text,
    inicio timestamptz NOT NULL,
    fin timestamptz NOT NULL,
    direccion text NOT NULL CHECK (btrim(direccion) <> ''),
    latitud numeric(9,6) CHECK (latitud BETWEEN -90 AND 90),
    longitud numeric(9,6) CHECK (longitud BETWEEN -180 AND 180),
    CHECK ((latitud IS NULL) = (longitud IS NULL)),
    apta_ninos boolean NOT NULL DEFAULT false,
    edad_minima smallint CHECK (edad_minima BETWEEN 0 AND 120),
    -- Una actividad apta para niños no puede pedir mayoría de edad
    CONSTRAINT actividades_apta_ninos_edad CHECK (NOT apta_ninos OR edad_minima IS NULL OR edad_minima < 18),
    cupo_total integer NOT NULL CHECK (cupo_total > 0),
    cupos_ocupados integer NOT NULL DEFAULT 0 CHECK (cupos_ocupados >= 0 AND cupos_ocupados <= cupo_total),
    foto_clave text,
    estado text NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador','publicada','cancelada','finalizada')),
    cancelada_en timestamptz,
    motivo_cancelacion text,
    CHECK ((estado = 'cancelada') = (cancelada_en IS NOT NULL)),
    creado_por uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    CHECK (fin > inicio),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE inscripciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    actividad_id uuid NOT NULL REFERENCES actividades(id) ON DELETE RESTRICT,
    estado text NOT NULL DEFAULT 'confirmada' CHECK (estado IN ('confirmada','cancelada')),
    cantidad_personas integer NOT NULL CHECK (cantidad_personas > 0),
    fecha_inscripcion timestamptz NOT NULL DEFAULT now(),
    cancelada_en timestamptz,
    motivo_cancelacion text CHECK (motivo_cancelacion IN ('usuario','actividad_cancelada','cuenta_eliminada')),
    UNIQUE (usuario_id, actividad_id),
    CHECK ((estado = 'cancelada') = (cancelada_en IS NOT NULL)),
    CHECK ((estado = 'cancelada') = (motivo_cancelacion IS NOT NULL)),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- nombre y edad_al_evento los calcula la base (trigger validar_asistente),
-- nunca se aceptan del cliente.
CREATE TABLE inscripcion_participantes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    inscripcion_id uuid NOT NULL REFERENCES inscripciones(id) ON DELETE CASCADE,
    miembro_comunidad_id uuid REFERENCES miembros_comunidad(id) ON DELETE RESTRICT,
    es_titular boolean NOT NULL DEFAULT false,
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    edad_al_evento smallint NOT NULL CHECK (edad_al_evento BETWEEN 0 AND 120),
    estado_asistencia text NOT NULL DEFAULT 'pendiente' CHECK (estado_asistencia IN ('pendiente','asistio','no_asistio')),
    asistencia_registrada_por uuid REFERENCES usuarios(id) ON DELETE RESTRICT,
    asistencia_registrada_en timestamptz,
    CHECK (es_titular = (miembro_comunidad_id IS NULL)),
    CHECK ((estado_asistencia = 'pendiente' AND asistencia_registrada_por IS NULL AND asistencia_registrada_en IS NULL)
        OR (estado_asistencia <> 'pendiente' AND asistencia_registrada_por IS NOT NULL AND asistencia_registrada_en IS NOT NULL)),
    UNIQUE (inscripcion_id, miembro_comunidad_id),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX un_titular_por_inscripcion ON inscripcion_participantes(inscripcion_id) WHERE es_titular;

-- ============================================================
-- Proyectos, campañas y donaciones en especie
-- ============================================================

CREATE TABLE proyectos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    asociacion_id uuid REFERENCES asociaciones(id) ON DELETE RESTRICT,
    titulo text NOT NULL CHECK (btrim(titulo) <> ''),
    descripcion text NOT NULL CHECK (btrim(descripcion) <> ''),
    fecha_inicio date NOT NULL,
    fecha_fin date,
    foto_clave text,
    estado text NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador','publicado','finalizado','cancelado')),
    creado_por uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- Una campaña pertenece al menos a una asociación o a un proyecto.
-- ciudad_id permite filtrar campañas por ciudad igual que las actividades.
CREATE TABLE campanas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proyecto_id uuid REFERENCES proyectos(id) ON DELETE RESTRICT,
    asociacion_id uuid REFERENCES asociaciones(id) ON DELETE RESTRICT,
    ciudad_id uuid NOT NULL REFERENCES ciudades(id) ON DELETE RESTRICT,
    titulo text NOT NULL CHECK (btrim(titulo) <> ''),
    descripcion text NOT NULL CHECK (btrim(descripcion) <> ''),
    inicio timestamptz NOT NULL,
    fin timestamptz NOT NULL,
    urgente boolean NOT NULL DEFAULT false,
    foto_clave text,
    estado text NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador','publicada','finalizada','cancelada')),
    creado_por uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    CONSTRAINT campanas_requiere_origen CHECK (num_nonnulls(proyecto_id, asociacion_id) >= 1),
    CHECK (fin > inicio),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- cantidad_recibida la mantiene el trigger de entregas_donacion
CREATE TABLE campana_articulos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campana_id uuid NOT NULL REFERENCES campanas(id) ON DELETE CASCADE,
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    descripcion text,
    unidad text NOT NULL CHECK (btrim(unidad) <> ''),
    cantidad_meta numeric(14,3) NOT NULL CHECK (cantidad_meta > 0),
    cantidad_recibida numeric(14,3) NOT NULL DEFAULT 0 CHECK (cantidad_recibida >= 0),
    prioridad text NOT NULL DEFAULT 'media' CHECK (prioridad IN ('baja','media','alta','urgente')),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE puntos_entrega (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campana_id uuid NOT NULL REFERENCES campanas(id) ON DELETE CASCADE,
    ciudad_id uuid NOT NULL REFERENCES ciudades(id) ON DELETE RESTRICT,
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    direccion text NOT NULL CHECK (btrim(direccion) <> ''),
    horarios text NOT NULL CHECK (btrim(horarios) <> ''),
    indicaciones text,
    latitud numeric(9,6) CHECK (latitud BETWEEN -90 AND 90),
    longitud numeric(9,6) CHECK (longitud BETWEEN -180 AND 180),
    CHECK ((latitud IS NULL) = (longitud IS NULL)),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- "Registrar mi entrega" de la app. La familia registra, un admin confirma
-- la recepción y solo entonces suma a cantidad_recibida.
CREATE TABLE entregas_donacion (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    articulo_id uuid NOT NULL REFERENCES campana_articulos(id) ON DELETE RESTRICT,
    punto_entrega_id uuid NOT NULL REFERENCES puntos_entrega(id) ON DELETE RESTRICT,
    cantidad numeric(14,3) NOT NULL CHECK (cantidad > 0),
    comentario text,
    estado text NOT NULL DEFAULT 'registrada' CHECK (estado IN ('registrada','recibida','cancelada')),
    recibida_por uuid REFERENCES usuarios(id) ON DELETE RESTRICT,
    recibida_en timestamptz,
    CHECK ((estado = 'recibida' AND recibida_por IS NOT NULL AND recibida_en IS NOT NULL)
        OR (estado <> 'recibida' AND recibida_por IS NULL AND recibida_en IS NULL)),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- Propuestas, testimonios, reportes, favoritos y valoraciones
-- ============================================================

-- Flujo válido en_revision -> necesita_cambios | aprobada | rechazada,
-- necesita_cambios -> en_revision, aprobada -> completada
CREATE TABLE propuestas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    tipo text NOT NULL DEFAULT 'iniciativa_vecinal' CHECK (tipo IN ('actividad','asociacion','iniciativa_vecinal')),
    titulo text NOT NULL CHECK (btrim(titulo) <> ''),
    descripcion text NOT NULL CHECK (btrim(descripcion) <> ''),
    ciudad_id uuid REFERENCES ciudades(id) ON DELETE RESTRICT,
    ubicacion text,
    contacto_nombre text,
    contacto_correo text,
    contacto_telefono text,
    estado text NOT NULL DEFAULT 'en_revision' CHECK (estado IN ('en_revision','necesita_cambios','aprobada','rechazada','completada')),
    comentario_admin text,
    revisado_por uuid REFERENCES usuarios(id) ON DELETE RESTRICT,
    revisado_en timestamptz,
    CHECK ((revisado_por IS NULL) = (revisado_en IS NULL)),
    CHECK (estado = 'en_revision' OR revisado_por IS NOT NULL),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- Línea de tiempo de EstadoPropuestaScreen. La llena un trigger.
CREATE TABLE propuesta_historial (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    propuesta_id uuid NOT NULL REFERENCES propuestas(id) ON DELETE CASCADE,
    estado text NOT NULL,
    comentario text,
    cambiado_por uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    cambiado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE testimonios (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    inscripcion_id uuid NOT NULL REFERENCES inscripciones(id) ON DELETE RESTRICT,
    texto text NOT NULL CHECK (btrim(texto) <> ''),
    foto_clave text NOT NULL CHECK (btrim(foto_clave) <> ''),
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','aprobado','rechazado')),
    comentario_admin text,
    revisado_por uuid REFERENCES usuarios(id) ON DELETE RESTRICT,
    revisado_en timestamptz,
    CHECK ((estado = 'pendiente' AND revisado_por IS NULL AND revisado_en IS NULL)
        OR (estado <> 'pendiente' AND revisado_por IS NOT NULL AND revisado_en IS NOT NULL)),
    UNIQUE (inscripcion_id),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- tipo corresponde a las opciones de ReportarExperienciaScreen y al botón
-- "Reportar asociación". Cada tipo exige su objetivo.
CREATE TABLE reportes_experiencia (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    actividad_id uuid REFERENCES actividades(id) ON DELETE RESTRICT,
    asociacion_id uuid REFERENCES asociaciones(id) ON DELETE RESTRICT,
    campana_id uuid REFERENCES campanas(id) ON DELETE RESTRICT,
    tipo text NOT NULL CHECK (tipo IN ('problema_actividad','problema_asociacion','problema_campana',
                                       'problema_aplicacion','comportamiento_inapropiado','otro')),
    nivel_satisfaccion smallint CHECK (nivel_satisfaccion BETWEEN 1 AND 5),
    descripcion text NOT NULL CHECK (btrim(descripcion) <> ''),
    foto_clave text,
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','en_revision','resuelto')),
    respuesta_admin text,
    atendido_por uuid REFERENCES usuarios(id) ON DELETE RESTRICT,
    atendido_en timestamptz,
    CONSTRAINT reportes_un_objetivo CHECK (num_nonnulls(actividad_id, asociacion_id, campana_id) <= 1),
    CONSTRAINT reportes_objetivo_actividad CHECK (tipo <> 'problema_actividad' OR actividad_id IS NOT NULL),
    CONSTRAINT reportes_objetivo_asociacion CHECK (tipo <> 'problema_asociacion' OR asociacion_id IS NOT NULL),
    CONSTRAINT reportes_objetivo_campana CHECK (tipo <> 'problema_campana' OR campana_id IS NOT NULL),
    CONSTRAINT reportes_aplicacion_sin_objetivo CHECK (tipo <> 'problema_aplicacion' OR num_nonnulls(actividad_id, asociacion_id, campana_id) = 0),
    CHECK ((atendido_por IS NULL) = (atendido_en IS NULL)),
    CHECK (estado = 'pendiente' OR atendido_por IS NOT NULL),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE favoritos_asociaciones (
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    asociacion_id uuid NOT NULL REFERENCES asociaciones(id) ON DELETE CASCADE,
    notificaciones_activas boolean NOT NULL DEFAULT false,
    creado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (usuario_id, asociacion_id)
);

CREATE TABLE favoritos_actividades (
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    actividad_id uuid NOT NULL REFERENCES actividades(id) ON DELETE CASCADE,
    creado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (usuario_id, actividad_id)
);

CREATE TABLE valoraciones_actividades (
    inscripcion_id uuid PRIMARY KEY REFERENCES inscripciones(id) ON DELETE RESTRICT,
    valor smallint NOT NULL CHECK (valor IN (-1, 1)),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE notificaciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo text NOT NULL CHECK (btrim(tipo) <> ''),
    titulo text NOT NULL CHECK (btrim(titulo) <> ''),
    mensaje text NOT NULL CHECK (btrim(mensaje) <> ''),
    actividad_id uuid REFERENCES actividades(id) ON DELETE RESTRICT,
    asociacion_id uuid REFERENCES asociaciones(id) ON DELETE RESTRICT,
    propuesta_id uuid REFERENCES propuestas(id) ON DELETE RESTRICT,
    campana_id uuid REFERENCES campanas(id) ON DELETE RESTRICT,
    CHECK (num_nonnulls(actividad_id, asociacion_id, propuesta_id, campana_id) <= 1),
    leida_en timestamptz,
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- Encuestas
-- ============================================================

CREATE TABLE encuestas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actividad_id uuid NOT NULL REFERENCES actividades(id) ON DELETE RESTRICT,
    titulo text NOT NULL CHECK (btrim(titulo) <> ''),
    momento text NOT NULL DEFAULT 'antes' CHECK (momento IN ('antes','despues')),
    activa boolean NOT NULL DEFAULT true,
    UNIQUE (actividad_id, momento),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE preguntas_encuesta (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    encuesta_id uuid NOT NULL REFERENCES encuestas(id) ON DELETE CASCADE,
    texto text NOT NULL CHECK (btrim(texto) <> ''),
    tipo text NOT NULL DEFAULT 'texto' CHECK (tipo IN ('texto','opcion_unica')),
    obligatoria boolean NOT NULL DEFAULT true,
    orden integer NOT NULL CHECK (orden > 0),
    UNIQUE (encuesta_id, orden),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE opciones_pregunta (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pregunta_id uuid NOT NULL REFERENCES preguntas_encuesta(id) ON DELETE CASCADE,
    texto text NOT NULL CHECK (btrim(texto) <> ''),
    orden integer NOT NULL CHECK (orden > 0),
    UNIQUE (pregunta_id, orden),
    UNIQUE (id, pregunta_id),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE respuestas_encuesta (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    inscripcion_id uuid NOT NULL REFERENCES inscripciones(id) ON DELETE RESTRICT,
    pregunta_id uuid NOT NULL REFERENCES preguntas_encuesta(id) ON DELETE RESTRICT,
    opcion_id uuid,
    respuesta_texto text,
    respondida_en timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (opcion_id, pregunta_id) REFERENCES opciones_pregunta(id, pregunta_id),
    CHECK (num_nonnulls(opcion_id, respuesta_texto) = 1),
    CHECK (respuesta_texto IS NULL OR btrim(respuesta_texto) <> ''),
    UNIQUE (inscripcion_id, pregunta_id),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- Reconocimiento
-- ============================================================

-- categoria_id NULL significa insignia general; con categoría cuenta solo
-- participaciones de esa categoría (por ejemplo "5x Naturaleza").
CREATE TABLE insignias (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    descripcion text NOT NULL CHECK (btrim(descripcion) <> ''),
    imagen_clave text,
    categoria_id uuid REFERENCES categorias(id) ON DELETE RESTRICT,
    participaciones_requeridas integer NOT NULL CHECK (participaciones_requeridas > 0),
    activa boolean NOT NULL DEFAULT true,
    UNIQUE (nombre),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE usuario_insignias (
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    insignia_id uuid NOT NULL REFERENCES insignias(id) ON DELETE RESTRICT,
    otorgada_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (usuario_id, insignia_id)
);

-- Nivel del perfil ("Embajadores Comunitarios"). El nivel de un usuario es el
-- de mayor participaciones_minimas que no supere sus participaciones.
CREATE TABLE niveles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre text NOT NULL CHECK (btrim(nombre) <> ''),
    descripcion text,
    participaciones_minimas integer NOT NULL CHECK (participaciones_minimas >= 0),
    UNIQUE (nombre),
    UNIQUE (participaciones_minimas),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- Privacidad
-- ============================================================

-- El aviso vigente es el de publicado_en más reciente. Debe existir al menos
-- uno antes de abrir el registro, porque la aceptación es obligatoria.
CREATE TABLE avisos_privacidad (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version text NOT NULL CHECK (btrim(version) <> ''),
    contenido text NOT NULL CHECK (btrim(contenido) <> ''),
    publicado_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (version)
);

CREATE TABLE aceptaciones_privacidad (
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    aviso_id uuid NOT NULL REFERENCES avisos_privacidad(id) ON DELETE RESTRICT,
    aceptado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (usuario_id, aviso_id)
);

CREATE TABLE solicitudes_eliminacion (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id uuid NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    solicitada_en timestamptz NOT NULL DEFAULT now(),
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','en_proceso','resuelta')),
    resuelta_en timestamptz,
    atendida_por uuid REFERENCES usuarios(id) ON DELETE RESTRICT,
    CHECK ((estado = 'resuelta') = (resuelta_en IS NOT NULL)),
    CHECK (estado = 'pendiente' OR atendida_por IS NOT NULL),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX una_solicitud_abierta ON solicitudes_eliminacion(usuario_id) WHERE estado <> 'resuelta';

-- ============================================================
-- Auditoría e índices de claves foráneas
-- ============================================================

CREATE FUNCTION tocar_actualizado() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.actualizado_en = now(); RETURN NEW; END $$;

-- Idempotente. Volver a llamarla al final de cada migración que agregue
-- tablas, así toda tabla nueva recibe su trigger e índices.
CREATE FUNCTION instalar_auditoria() RETURNS void
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE t record; c record;
BEGIN
 FOR t IN SELECT col.table_name
          FROM information_schema.columns col
          JOIN information_schema.tables tb
            ON tb.table_schema = col.table_schema AND tb.table_name = col.table_name
          WHERE col.table_schema = 'fqs' AND col.column_name = 'actualizado_en'
            AND tb.table_type = 'BASE TABLE' LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER tocar_actualizado BEFORE UPDATE ON fqs.%I '
              || 'FOR EACH ROW EXECUTE FUNCTION fqs.tocar_actualizado()', t.table_name);
 END LOOP;
 FOR c IN SELECT cl.relname AS tabla,
                 string_agg(quote_ident(a.attname), ', ' ORDER BY k.ord) AS columnas,
                 string_agg(a.attname, '_' ORDER BY k.ord) AS nombre
          FROM pg_constraint co
          JOIN pg_class cl ON cl.oid = co.conrelid
          JOIN pg_namespace ns ON ns.oid = cl.relnamespace
          CROSS JOIN LATERAL unnest(co.conkey) WITH ORDINALITY AS k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = k.attnum
          WHERE ns.nspname = 'fqs' AND co.contype = 'f'
          GROUP BY co.oid, cl.relname LOOP
  EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON fqs.%I(%s)',
                 left(c.tabla || '_' || c.nombre || '_idx', 63), c.tabla, c.columnas);
 END LOOP;
END $$;

-- ============================================================
-- Validaciones generales
-- ============================================================

-- Las columnas indicadas en los argumentos del trigger deben apuntar a un
-- administrador activo. Solo se revisa cuando el valor cambia.
CREATE FUNCTION exigir_admin() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE col text; valor uuid;
BEGIN
 FOREACH col IN ARRAY TG_ARGV LOOP
  valor = CAST(to_jsonb(NEW) ->> col AS uuid);
  IF valor IS NOT NULL
     AND (TG_OP = 'INSERT' OR valor IS DISTINCT FROM CAST(to_jsonb(OLD) ->> col AS uuid))
     AND NOT EXISTS (SELECT 1 FROM usuarios WHERE id = valor AND rol = 'admin' AND estado = 'activo') THEN
   RAISE EXCEPTION 'La columna % requiere un administrador activo', col;
  END IF;
 END LOOP;
 RETURN NEW;
END $$;

CREATE TRIGGER admin_creador BEFORE INSERT OR UPDATE ON asociaciones
FOR EACH ROW EXECUTE FUNCTION exigir_admin('creado_por');
CREATE TRIGGER admin_creador BEFORE INSERT OR UPDATE ON actividades
FOR EACH ROW EXECUTE FUNCTION exigir_admin('creado_por');
CREATE TRIGGER admin_creador BEFORE INSERT OR UPDATE ON proyectos
FOR EACH ROW EXECUTE FUNCTION exigir_admin('creado_por');
CREATE TRIGGER admin_creador BEFORE INSERT OR UPDATE ON campanas
FOR EACH ROW EXECUTE FUNCTION exigir_admin('creado_por');
CREATE TRIGGER admin_asistencia BEFORE INSERT OR UPDATE ON inscripcion_participantes
FOR EACH ROW EXECUTE FUNCTION exigir_admin('asistencia_registrada_por');
CREATE TRIGGER admin_recepcion BEFORE INSERT OR UPDATE ON entregas_donacion
FOR EACH ROW EXECUTE FUNCTION exigir_admin('recibida_por');
CREATE TRIGGER admin_revision BEFORE INSERT OR UPDATE ON propuestas
FOR EACH ROW EXECUTE FUNCTION exigir_admin('revisado_por');
CREATE TRIGGER admin_revision BEFORE INSERT OR UPDATE ON testimonios
FOR EACH ROW EXECUTE FUNCTION exigir_admin('revisado_por');
CREATE TRIGGER admin_atencion BEFORE INSERT OR UPDATE ON reportes_experiencia
FOR EACH ROW EXECUTE FUNCTION exigir_admin('atendido_por');
CREATE TRIGGER admin_atencion BEFORE INSERT OR UPDATE ON solicitudes_eliminacion
FOR EACH ROW EXECUTE FUNCTION exigir_admin('atendida_por');

CREATE FUNCTION validar_nacimiento() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.fecha_nacimiento > CURRENT_DATE THEN RAISE EXCEPTION 'La fecha de nacimiento no puede ser futura'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER validar_nacimiento BEFORE INSERT OR UPDATE OF fecha_nacimiento ON usuarios
FOR EACH ROW EXECUTE FUNCTION validar_nacimiento();
CREATE TRIGGER validar_nacimiento BEFORE INSERT OR UPDATE OF fecha_nacimiento ON miembros_comunidad
FOR EACH ROW EXECUTE FUNCTION validar_nacimiento();

CREATE FUNCTION validar_miembro() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.usuario_id <> OLD.usuario_id THEN RAISE EXCEPTION 'No se puede transferir un acompañante a otra cuenta'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER validar_miembro BEFORE UPDATE OF usuario_id ON miembros_comunidad
FOR EACH ROW EXECUTE FUNCTION validar_miembro();

CREATE FUNCTION validar_campana() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE asociacion_proyecto uuid;
BEGIN
 IF NEW.proyecto_id IS NOT NULL AND NEW.asociacion_id IS NOT NULL THEN
  SELECT asociacion_id INTO asociacion_proyecto FROM proyectos WHERE id = NEW.proyecto_id;
  IF asociacion_proyecto IS NOT NULL AND asociacion_proyecto <> NEW.asociacion_id THEN
   RAISE EXCEPTION 'La asociación de la campaña no coincide con la del proyecto';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER validar_campana BEFORE INSERT OR UPDATE OF proyecto_id, asociacion_id ON campanas
FOR EACH ROW EXECUTE FUNCTION validar_campana();

-- ============================================================
-- Cupos e inscripciones
-- ============================================================

-- Contador transaccional. Toda modificación de una reserva aplica un delta
-- atómico a la misma fila de actividad. El CHECK impide sobrecupo incluso con
-- concurrencia, y reducir el cupo por debajo de lo ocupado también falla.
CREATE FUNCTION ajustar_cupos() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE antes integer = 0; despues integer = 0; actividad uuid;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  actividad = OLD.actividad_id;
  IF OLD.estado = 'confirmada' THEN antes = OLD.cantidad_personas; END IF;
 END IF;
 IF TG_OP <> 'DELETE' THEN
  actividad = NEW.actividad_id;
  IF TG_OP = 'UPDATE' AND (NEW.actividad_id <> OLD.actividad_id OR NEW.usuario_id <> OLD.usuario_id) THEN
   RAISE EXCEPTION 'La identidad de una inscripción no se puede cambiar';
  END IF;
  IF NEW.estado = 'confirmada' THEN despues = NEW.cantidad_personas; END IF;
 END IF;
 IF despues <> antes THEN
  UPDATE actividades SET cupos_ocupados = cupos_ocupados + despues - antes
  WHERE id = actividad AND cupos_ocupados + despues - antes BETWEEN 0 AND cupo_total;
  IF NOT FOUND THEN RAISE EXCEPTION 'Cupo insuficiente o reserva inconsistente'; END IF;
 END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER reservar_cupos BEFORE INSERT OR UPDATE OR DELETE ON inscripciones
FOR EACH ROW EXECUTE FUNCTION ajustar_cupos();

-- Al confirmar la transacción, la reserva debe coincidir con sus asistentes.
CREATE FUNCTION comprobar_participantes() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE ids uuid[]; x uuid; esperado integer; encontrados bigint;
BEGIN
 IF TG_TABLE_NAME = 'inscripciones' THEN
  ids = ARRAY[NEW.id];
 ELSIF TG_OP = 'INSERT' THEN ids = ARRAY[NEW.inscripcion_id];
 ELSIF TG_OP = 'DELETE' THEN ids = ARRAY[OLD.inscripcion_id];
 ELSE ids = ARRAY[OLD.inscripcion_id, NEW.inscripcion_id];
 END IF;
 FOREACH x IN ARRAY ids LOOP
  SELECT cantidad_personas INTO esperado FROM inscripciones WHERE id = x;
  IF FOUND THEN
   SELECT count(*) INTO encontrados FROM inscripcion_participantes WHERE inscripcion_id = x;
   IF encontrados <> esperado THEN
    RAISE EXCEPTION 'La cantidad reservada (%) no coincide con los participantes (%)', esperado, encontrados;
   END IF;
  END IF;
 END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER cantidad_reserva AFTER INSERT OR UPDATE ON inscripciones
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION comprobar_participantes();
CREATE CONSTRAINT TRIGGER cantidad_asistentes AFTER INSERT OR UPDATE OR DELETE ON inscripcion_participantes
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION comprobar_participantes();

-- Nombre y edad salen siempre de la base (usuario o miembro), nunca del cliente.
-- La edad se calcula al día del evento en la zona horaria de su ciudad.
CREATE FUNCTION validar_participante() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE titular uuid; inicio_evento timestamptz; zona text; edad_requerida integer;
 nacimiento date; nombre_real text; dueno uuid; miembro_activo boolean;
BEGIN
 SELECT i.usuario_id, a.inicio, c.zona_horaria, COALESCE(a.edad_minima, 0)
   INTO titular, inicio_evento, zona, edad_requerida
 FROM inscripciones i
 JOIN actividades a ON a.id = i.actividad_id
 JOIN ciudades c ON c.id = a.ciudad_id
 WHERE i.id = NEW.inscripcion_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Inscripción inexistente'; END IF;
 IF NEW.es_titular THEN
  SELECT fecha_nacimiento, nombre INTO nacimiento, nombre_real FROM usuarios WHERE id = titular;
  IF nacimiento IS NULL THEN
   RAISE EXCEPTION 'El titular debe registrar su fecha de nacimiento para asistir';
  END IF;
 ELSE
  SELECT usuario_id, activo, fecha_nacimiento, nombre
    INTO dueno, miembro_activo, nacimiento, nombre_real
  FROM miembros_comunidad WHERE id = NEW.miembro_comunidad_id FOR SHARE;
  IF NOT FOUND OR dueno <> titular OR NOT miembro_activo THEN
   RAISE EXCEPTION 'Acompañante ajeno, inactivo o inexistente';
  END IF;
 END IF;
 NEW.nombre = nombre_real;
 NEW.edad_al_evento = extract(year FROM age(CAST(inicio_evento AT TIME ZONE zona AS date), nacimiento));
 IF NEW.edad_al_evento < edad_requerida THEN
  RAISE EXCEPTION '% no cumple la edad mínima de % años', nombre_real, edad_requerida;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER validar_asistente
BEFORE INSERT OR UPDATE OF inscripcion_id, miembro_comunidad_id, es_titular, edad_al_evento
ON inscripcion_participantes FOR EACH ROW EXECUTE FUNCTION validar_participante();

-- La asistencia solo se registra cuando la actividad ya empezó y la
-- inscripción sigue confirmada. La hora del registro la pone la base.
CREATE FUNCTION validar_asistencia() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE inicio_evento timestamptz; estado_inscripcion text;
BEGIN
 IF NEW.estado_asistencia IS NOT DISTINCT FROM OLD.estado_asistencia THEN RETURN NEW; END IF;
 IF NEW.estado_asistencia = 'pendiente' THEN
  NEW.asistencia_registrada_por = NULL;
  NEW.asistencia_registrada_en = NULL;
  RETURN NEW;
 END IF;
 SELECT a.inicio, i.estado INTO inicio_evento, estado_inscripcion
 FROM inscripciones i JOIN actividades a ON a.id = i.actividad_id
 WHERE i.id = NEW.inscripcion_id;
 IF estado_inscripcion <> 'confirmada' THEN
  RAISE EXCEPTION 'No se registra asistencia de una inscripción cancelada';
 END IF;
 IF now() < inicio_evento THEN
  RAISE EXCEPTION 'No se puede registrar asistencia antes de que empiece la actividad';
 END IF;
 NEW.asistencia_registrada_en = now();
 RETURN NEW;
END $$;
CREATE TRIGGER validar_asistencia BEFORE UPDATE OF estado_asistencia ON inscripcion_participantes
FOR EACH ROW EXECUTE FUNCTION validar_asistencia();

-- Una actividad con inscripciones confirmadas solo se cancela con cancelar_actividad,
-- que también cancela las inscripciones y avisa a las familias.
CREATE FUNCTION proteger_cancelacion() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 IF NEW.estado = 'cancelada' AND OLD.estado <> 'cancelada' THEN
  IF EXISTS (SELECT 1 FROM inscripciones WHERE actividad_id = NEW.id AND estado = 'confirmada') THEN
   RAISE EXCEPTION 'La actividad tiene inscripciones confirmadas, usa cancelar_actividad';
  END IF;
  NEW.cancelada_en = COALESCE(NEW.cancelada_en, now());
 ELSIF NEW.estado <> 'cancelada' THEN
  NEW.cancelada_en = NULL;
  NEW.motivo_cancelacion = NULL;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER proteger_cancelacion BEFORE UPDATE OF estado ON actividades
FOR EACH ROW EXECUTE FUNCTION proteger_cancelacion();

-- ============================================================
-- Experiencia, encuestas, donaciones y propuestas
-- ============================================================

CREATE FUNCTION validar_experiencia() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM inscripciones i
                JOIN inscripcion_participantes p ON p.inscripcion_id = i.id
                WHERE i.id = NEW.inscripcion_id AND i.estado = 'confirmada'
                  AND p.estado_asistencia = 'asistio') THEN
  RAISE EXCEPTION 'Se requiere una participación con asistencia confirmada';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER experiencia_testimonio BEFORE INSERT OR UPDATE OF inscripcion_id ON testimonios
FOR EACH ROW EXECUTE FUNCTION validar_experiencia();
CREATE TRIGGER experiencia_valoracion BEFORE INSERT OR UPDATE OF inscripcion_id ON valoraciones_actividades
FOR EACH ROW EXECUTE FUNCTION validar_experiencia();

-- La encuesta debe estar activa y ser de la actividad inscrita. La de "antes"
-- se responde hasta que termina la actividad, la de "despues" exige asistencia.
CREATE FUNCTION validar_respuesta() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE tipo_pregunta text; actividad_encuesta uuid; momento_encuesta text; encuesta_activa boolean;
 actividad_inscripcion uuid; estado_inscripcion text; fin_evento timestamptz;
BEGIN
 SELECT p.tipo, e.actividad_id, e.momento, e.activa
   INTO tipo_pregunta, actividad_encuesta, momento_encuesta, encuesta_activa
 FROM preguntas_encuesta p JOIN encuestas e ON e.id = p.encuesta_id WHERE p.id = NEW.pregunta_id;
 SELECT i.actividad_id, i.estado, a.fin INTO actividad_inscripcion, estado_inscripcion, fin_evento
 FROM inscripciones i JOIN actividades a ON a.id = i.actividad_id WHERE i.id = NEW.inscripcion_id;
 IF actividad_encuesta IS NULL OR actividad_encuesta IS DISTINCT FROM actividad_inscripcion THEN
  RAISE EXCEPTION 'La encuesta no corresponde a la actividad inscrita';
 END IF;
 IF NOT encuesta_activa THEN RAISE EXCEPTION 'La encuesta no está activa'; END IF;
 IF estado_inscripcion <> 'confirmada' THEN RAISE EXCEPTION 'La inscripción está cancelada'; END IF;
 IF momento_encuesta = 'antes' AND now() >= fin_evento THEN
  RAISE EXCEPTION 'La encuesta previa ya cerró';
 END IF;
 IF momento_encuesta = 'despues' AND NOT EXISTS (
     SELECT 1 FROM inscripcion_participantes
     WHERE inscripcion_id = NEW.inscripcion_id AND estado_asistencia = 'asistio') THEN
  RAISE EXCEPTION 'La encuesta posterior requiere asistencia confirmada';
 END IF;
 IF (tipo_pregunta = 'texto' AND NEW.respuesta_texto IS NULL)
    OR (tipo_pregunta = 'opcion_unica' AND NEW.opcion_id IS NULL) THEN
  RAISE EXCEPTION 'Tipo de respuesta incorrecto';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER respuesta_coherente BEFORE INSERT OR UPDATE ON respuestas_encuesta
FOR EACH ROW EXECUTE FUNCTION validar_respuesta();

-- Artículo y punto de entrega deben ser de la misma campaña, y solo se
-- registran entregas nuevas en campañas publicadas y vigentes.
CREATE FUNCTION validar_entrega() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE campana_articulo uuid; campana_punto uuid; c campanas%ROWTYPE;
BEGIN
 IF TG_OP = 'UPDATE' AND (NEW.usuario_id <> OLD.usuario_id OR NEW.articulo_id <> OLD.articulo_id) THEN
  RAISE EXCEPTION 'La identidad de una entrega no se puede cambiar';
 END IF;
 SELECT campana_id INTO campana_articulo FROM campana_articulos WHERE id = NEW.articulo_id;
 SELECT campana_id INTO campana_punto FROM puntos_entrega WHERE id = NEW.punto_entrega_id;
 IF campana_articulo IS DISTINCT FROM campana_punto THEN
  RAISE EXCEPTION 'El punto de entrega no pertenece a la campaña del artículo';
 END IF;
 IF TG_OP = 'INSERT' THEN
  SELECT * INTO c FROM campanas WHERE id = campana_articulo;
  IF c.estado <> 'publicada' OR now() NOT BETWEEN c.inicio AND c.fin THEN
   RAISE EXCEPTION 'La campaña no está recibiendo donaciones';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM usuarios WHERE id = NEW.usuario_id AND estado = 'activo') THEN
   RAISE EXCEPTION 'Usuario inexistente o inactivo';
  END IF;
 END IF;
 IF NEW.estado = 'recibida' AND (TG_OP = 'INSERT' OR OLD.estado <> 'recibida') THEN
  NEW.recibida_en = now();
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER validar_entrega BEFORE INSERT OR UPDATE ON entregas_donacion
FOR EACH ROW EXECUTE FUNCTION validar_entrega();

-- Mismo patrón de delta que los cupos, solo cuentan las entregas recibidas.
CREATE FUNCTION ajustar_recibido() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE antes numeric = 0; despues numeric = 0; articulo uuid;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  articulo = OLD.articulo_id;
  IF OLD.estado = 'recibida' THEN antes = OLD.cantidad; END IF;
 END IF;
 IF TG_OP <> 'DELETE' THEN
  articulo = NEW.articulo_id;
  IF NEW.estado = 'recibida' THEN despues = NEW.cantidad; END IF;
 END IF;
 IF despues <> antes THEN
  UPDATE campana_articulos SET cantidad_recibida = cantidad_recibida + despues - antes
  WHERE id = articulo;
 END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER sumar_recibido AFTER INSERT OR UPDATE OR DELETE ON entregas_donacion
FOR EACH ROW EXECUTE FUNCTION ajustar_recibido();

CREATE FUNCTION validar_propuesta() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 IF TG_OP = 'INSERT' THEN
  IF NEW.estado <> 'en_revision' THEN RAISE EXCEPTION 'Una propuesta nueva entra en revisión'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.usuario_id <> OLD.usuario_id THEN RAISE EXCEPTION 'No se puede cambiar el autor de una propuesta'; END IF;
 IF NEW.estado IS DISTINCT FROM OLD.estado THEN
  IF NOT ((OLD.estado = 'en_revision' AND NEW.estado IN ('necesita_cambios','aprobada','rechazada'))
       OR (OLD.estado = 'necesita_cambios' AND NEW.estado = 'en_revision')
       OR (OLD.estado = 'aprobada' AND NEW.estado = 'completada')) THEN
   RAISE EXCEPTION 'Transición de propuesta no permitida (% a %)', OLD.estado, NEW.estado;
  END IF;
  IF NEW.estado = 'en_revision' THEN
   -- La familia reenvía tras corregir, el comentario anterior ya no aplica
   NEW.comentario_admin = NULL;
  ELSE
   NEW.revisado_en = now();
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER validar_propuesta BEFORE INSERT OR UPDATE ON propuestas
FOR EACH ROW EXECUTE FUNCTION validar_propuesta();

CREATE FUNCTION registrar_historial_propuesta() RETURNS trigger
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 IF TG_OP = 'INSERT' OR NEW.estado IS DISTINCT FROM OLD.estado THEN
  INSERT INTO propuesta_historial(propuesta_id, estado, comentario, cambiado_por)
  VALUES (NEW.id, NEW.estado,
          CASE WHEN NEW.estado = 'en_revision' THEN NULL ELSE NEW.comentario_admin END,
          CASE WHEN NEW.estado = 'en_revision' THEN NEW.usuario_id ELSE NEW.revisado_por END);
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER historial_propuesta AFTER INSERT OR UPDATE OF estado ON propuestas
FOR EACH ROW EXECUTE FUNCTION registrar_historial_propuesta();

-- ============================================================
-- Funciones de negocio para la API
-- p_usuario y p_admin salen SIEMPRE de la sesión autenticada (JWT), nunca del cliente.
-- ============================================================

CREATE FUNCTION exigir_admin_activo(p_admin uuid) RETURNS void
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM usuarios WHERE id = p_admin AND rol = 'admin' AND estado = 'activo') THEN
  RAISE EXCEPTION 'Operación reservada a administradores';
 END IF;
END $$;

-- p_titular_asiste indica si el titular va. Su edad sale de usuarios.fecha_nacimiento.
-- p_miembros son UUIDs de su propia comunidad. Una reserva confirmada no se reemplaza.
CREATE FUNCTION inscribir_familia(p_usuario uuid, p_actividad uuid,
 p_titular_asiste boolean DEFAULT false, p_miembros uuid[] DEFAULT '{}')
RETURNS uuid LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE a actividades%ROWTYPE; reserva uuid; estado_previo text; n integer;
BEGIN
 IF p_titular_asiste IS NULL OR p_miembros IS NULL OR array_position(p_miembros, NULL) IS NOT NULL THEN
  RAISE EXCEPTION 'Parámetros inválidos';
 END IF;
 IF cardinality(p_miembros) <> (SELECT count(DISTINCT x) FROM unnest(p_miembros) x) THEN
  RAISE EXCEPTION 'Acompañantes repetidos';
 END IF;
 PERFORM 1 FROM usuarios WHERE id = p_usuario AND estado = 'activo' AND rol = 'familia' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Usuario inexistente, inactivo o sin cuenta de familia'; END IF;
 SELECT * INTO a FROM actividades WHERE id = p_actividad FOR UPDATE;
 IF NOT FOUND OR a.estado <> 'publicada' OR a.inicio <= now() THEN
  RAISE EXCEPTION 'Actividad no disponible para inscripción';
 END IF;
 n = cardinality(p_miembros) + CASE WHEN p_titular_asiste THEN 1 ELSE 0 END;
 IF n = 0 THEN RAISE EXCEPTION 'Debe asistir al menos una persona'; END IF;
 SELECT id, estado INTO reserva, estado_previo FROM inscripciones
 WHERE usuario_id = p_usuario AND actividad_id = p_actividad FOR UPDATE;
 IF estado_previo = 'confirmada' THEN RAISE EXCEPTION 'Ya existe una inscripción confirmada'; END IF;
 IF reserva IS NULL THEN
  INSERT INTO inscripciones(usuario_id, actividad_id, cantidad_personas)
  VALUES (p_usuario, p_actividad, n) RETURNING id INTO reserva;
 ELSE
  DELETE FROM inscripcion_participantes WHERE inscripcion_id = reserva;
  UPDATE inscripciones
  SET cantidad_personas = n, estado = 'confirmada', cancelada_en = NULL,
      motivo_cancelacion = NULL, fecha_inscripcion = now()
  WHERE id = reserva;
 END IF;
 IF p_titular_asiste THEN
  INSERT INTO inscripcion_participantes(inscripcion_id, es_titular) VALUES (reserva, true);
 END IF;
 INSERT INTO inscripcion_participantes(inscripcion_id, miembro_comunidad_id)
 SELECT reserva, x FROM unnest(p_miembros) x;
 RETURN reserva;
END $$;

CREATE FUNCTION cancelar_inscripcion(p_usuario uuid, p_actividad uuid) RETURNS void
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 PERFORM 1 FROM actividades WHERE id = p_actividad AND inicio > now() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Actividad inexistente o ya iniciada'; END IF;
 UPDATE inscripciones SET estado = 'cancelada', cancelada_en = now(), motivo_cancelacion = 'usuario'
 WHERE usuario_id = p_usuario AND actividad_id = p_actividad AND estado = 'confirmada';
 IF NOT FOUND THEN RAISE EXCEPTION 'No hay inscripción confirmada'; END IF;
END $$;

-- Cancela la actividad, libera los cupos y deja una notificación a cada familia.
-- Devuelve cuántas inscripciones se cancelaron.
CREATE FUNCTION cancelar_actividad(p_admin uuid, p_actividad uuid, p_motivo text)
RETURNS integer LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE a actividades%ROWTYPE; afectadas integer;
BEGIN
 PERFORM exigir_admin_activo(p_admin);
 IF p_motivo IS NULL OR btrim(p_motivo) = '' THEN RAISE EXCEPTION 'Indica el motivo de la cancelación'; END IF;
 SELECT * INTO a FROM actividades WHERE id = p_actividad FOR UPDATE;
 IF NOT FOUND OR a.estado NOT IN ('borrador','publicada') THEN
  RAISE EXCEPTION 'La actividad no existe o ya no se puede cancelar';
 END IF;
 WITH canceladas AS (
  UPDATE inscripciones SET estado = 'cancelada', cancelada_en = now(), motivo_cancelacion = 'actividad_cancelada'
  WHERE actividad_id = p_actividad AND estado = 'confirmada'
  RETURNING usuario_id
 )
 INSERT INTO notificaciones(usuario_id, tipo, titulo, mensaje, actividad_id)
 SELECT usuario_id, 'actividad_cancelada', 'Actividad cancelada',
        format('La actividad "%s" fue cancelada (%s).', a.titulo, p_motivo), p_actividad
 FROM canceladas;
 GET DIAGNOSTICS afectadas = ROW_COUNT;
 UPDATE actividades SET estado = 'cancelada', cancelada_en = now(), motivo_cancelacion = p_motivo
 WHERE id = p_actividad;
 RETURN afectadas;
END $$;

-- Botón "Eliminar" de Mi Comunidad. Si el miembro tiene historial se desactiva
-- en lugar de borrarse. Devuelve 'eliminado' o 'desactivado'.
CREATE FUNCTION eliminar_miembro(p_usuario uuid, p_miembro uuid) RETURNS text
LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
BEGIN
 PERFORM 1 FROM miembros_comunidad WHERE id = p_miembro AND usuario_id = p_usuario FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Acompañante inexistente o ajeno'; END IF;
 IF EXISTS (SELECT 1 FROM inscripcion_participantes p
            JOIN inscripciones i ON i.id = p.inscripcion_id
            JOIN actividades a ON a.id = i.actividad_id
            WHERE p.miembro_comunidad_id = p_miembro AND i.estado = 'confirmada' AND a.inicio > now()) THEN
  RAISE EXCEPTION 'El acompañante está inscrito en una actividad próxima, cancela esa inscripción primero';
 END IF;
 IF EXISTS (SELECT 1 FROM inscripcion_participantes WHERE miembro_comunidad_id = p_miembro) THEN
  UPDATE miembros_comunidad SET activo = false WHERE id = p_miembro;
  RETURN 'desactivado';
 END IF;
 DELETE FROM miembros_comunidad WHERE id = p_miembro;
 RETURN 'eliminado';
END $$;

-- Atiende una solicitud de eliminación (derechos ARCO). Conserva el historial
-- estadístico pero borra o reemplaza todo dato personal. Devuelve las claves
-- de archivos (fotos) que el backend debe borrar del almacenamiento.
CREATE FUNCTION anonimizar_usuario(p_admin uuid, p_solicitud uuid)
RETURNS TABLE (archivo text) LANGUAGE plpgsql SET search_path = fqs, pg_catalog AS $$
DECLARE uid uuid; fotos text[];
BEGIN
 PERFORM exigir_admin_activo(p_admin);
 SELECT usuario_id INTO uid FROM solicitudes_eliminacion
 WHERE id = p_solicitud AND estado <> 'resuelta' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Solicitud inexistente o ya resuelta'; END IF;
 PERFORM 1 FROM usuarios WHERE id = uid FOR UPDATE;

 SELECT array_remove(array_agg(f), NULL) INTO fotos FROM (
  SELECT foto_clave AS f FROM usuarios WHERE id = uid
  UNION ALL
  SELECT t.foto_clave FROM testimonios t JOIN inscripciones i ON i.id = t.inscripcion_id WHERE i.usuario_id = uid
  UNION ALL
  SELECT foto_clave FROM reportes_experiencia WHERE usuario_id = uid
 ) s;

 UPDATE inscripciones i SET estado = 'cancelada', cancelada_en = now(), motivo_cancelacion = 'cuenta_eliminada'
 FROM actividades a
 WHERE a.id = i.actividad_id AND i.usuario_id = uid AND i.estado = 'confirmada' AND a.inicio > now();

 UPDATE inscripcion_participantes p SET nombre = 'Participante'
 FROM inscripciones i WHERE i.id = p.inscripcion_id AND i.usuario_id = uid;

 -- Fecha fija porque la columna es obligatoria; las edades ya quedaron guardadas en cada participación.
 UPDATE miembros_comunidad
 SET nombre = 'Acompañante', relacion = 'Otro', correo = NULL, telefono = NULL,
     fecha_nacimiento = DATE '1900-01-01', activo = false
 WHERE usuario_id = uid;

 DELETE FROM testimonios t USING inscripciones i WHERE i.id = t.inscripcion_id AND i.usuario_id = uid;
 DELETE FROM respuestas_encuesta r USING inscripciones i
 WHERE i.id = r.inscripcion_id AND i.usuario_id = uid AND r.respuesta_texto IS NOT NULL;
 UPDATE reportes_experiencia SET foto_clave = NULL WHERE usuario_id = uid;
 UPDATE propuestas SET contacto_nombre = NULL, contacto_correo = NULL, contacto_telefono = NULL
 WHERE usuario_id = uid;

 DELETE FROM favoritos_asociaciones WHERE usuario_id = uid;
 DELETE FROM favoritos_actividades WHERE usuario_id = uid;
 DELETE FROM usuario_categorias WHERE usuario_id = uid;
 DELETE FROM usuario_preferencias WHERE usuario_id = uid;
 DELETE FROM dispositivos WHERE usuario_id = uid;
 DELETE FROM tokens_recuperacion WHERE usuario_id = uid;
 DELETE FROM notificaciones WHERE usuario_id = uid;

 UPDATE usuarios
 SET nombre = 'Usuario eliminado', username = 'eliminado_' || CAST(uid AS text),
     correo = NULL, telefono = NULL, password_hash = '!', fecha_nacimiento = NULL,
     foto_clave = NULL, ciudad_id = NULL, estado = 'eliminado'
 WHERE id = uid;

 UPDATE solicitudes_eliminacion
 SET estado = 'resuelta', resuelta_en = now(), atendida_por = p_admin
 WHERE id = p_solicitud;

 RETURN QUERY SELECT unnest(COALESCE(fotos, '{}'));
END $$;

-- ============================================================
-- Vistas
-- ============================================================

CREATE VIEW actividades_disponibilidad AS
SELECT a.*, a.cupo_total - a.cupos_ocupados AS cupos_disponibles FROM actividades a;

CREATE VIEW testimonios_publicados AS
SELECT id, inscripcion_id, texto, foto_clave, creado_en FROM testimonios WHERE estado = 'aprobado';

CREATE VIEW campanas_avance AS
SELECT ca.id, ca.campana_id, ca.nombre, ca.unidad, ca.prioridad, ca.cantidad_meta, ca.cantidad_recibida,
       round(100 * ca.cantidad_recibida / ca.cantidad_meta, 2) AS porcentaje
FROM campana_articulos ca;

-- Base para insignias, nivel e historial del perfil. Una participación es
-- una inscripción confirmada con al menos una asistencia.
CREATE VIEW participaciones_usuario AS
SELECT i.usuario_id, a.categoria_id, count(*) AS participaciones
FROM inscripciones i
JOIN actividades a ON a.id = i.actividad_id
WHERE i.estado = 'confirmada'
  AND EXISTS (SELECT 1 FROM inscripcion_participantes p
              WHERE p.inscripcion_id = i.id AND p.estado_asistencia = 'asistio')
GROUP BY i.usuario_id, a.categoria_id;

CREATE VIEW aviso_privacidad_vigente AS
SELECT * FROM avisos_privacidad ORDER BY publicado_en DESC LIMIT 1;

-- ============================================================
-- Índices y permisos
-- ============================================================

DO $$ BEGIN PERFORM fqs.instalar_auditoria(); END $$;
CREATE INDEX actividades_busqueda ON actividades(ciudad_id, estado, inicio);
CREATE INDEX campanas_busqueda ON campanas(ciudad_id, estado, fin);
CREATE INDEX notificaciones_pendientes ON notificaciones(usuario_id, creado_en DESC) WHERE leida_en IS NULL;

-- La app Android jamás se conecta a PostgreSQL. El backend usa el rol de 03_roles.sql.
REVOKE ALL ON SCHEMA fqs FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA fqs FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA fqs FROM PUBLIC;
COMMIT;
