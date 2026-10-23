// Catálogos, reconocimientos, aviso de privacidad y seguridad de la cuenta de administración
// (segundo factor, sesiones abiertas, bitácora y alertas).

import { borrar, catalogos, conFiltros, get, post } from '../api.js';
import { aviso, botonAccion, chip, dialogo, el, fechaHora, ficha, formulario, siNo, tabla, vaciar } from '../ui.js';

const encabezado = (titulo, ...extra) => el('div', { class: 'encabezado' }, el('h1', { text: titulo }), el('div', {}, extra));

const ZONAS = [
  'America/Mexico_City',
  'America/Monterrey',
  'America/Merida',
  'America/Cancun',
  'America/Chihuahua',
  'America/Ciudad_Juarez',
  'America/Hermosillo',
  'America/Mazatlan',
  'America/Tijuana',
  'America/Matamoros',
  'America/Bahia_Banderas',
].map((z) => ({ valor: z, texto: z.replace('America/', '').replace('_', ' ') }));

/** Formulario dentro de un diálogo que al guardar cierra y recarga la vista. */
function enDialogo(titulo, campos, enviar, recargar, opciones = {}) {
  let cerrar = null;
  const f = formulario(campos, {
    ...opciones,
    alCancelar: () => cerrar(),
    enviar: async (d) => {
      await enviar(d);
      cerrar();
      aviso('Guardado');
      recargar();
    },
  });
  cerrar = dialogo(titulo, f);
}

// ---------------- Ciudades y categorías ----------------

async function catalogosVista({ recargar }) {
  const cat = await catalogos(true);
  return el(
    'div',
    {},
    encabezado('Ciudades y categorías'),
    el('h2', { text: 'Ciudades' }),
    el('div', { class: 'barra' },
      el('button', {
        type: 'button',
        class: 'primario',
        text: 'Agregar ciudad',
        onclick: () =>
          enDialogo(
            'Nueva ciudad',
            [
              { nombre: 'nombre', etiqueta: 'Nombre', requerido: true, largo: 100 },
              { nombre: 'estado', etiqueta: 'Estado', requerido: true, largo: 100 },
              { nombre: 'zonaHoraria', etiqueta: 'Zona horaria', tipo: 'select', requerido: true, opciones: ZONAS },
            ],
            (d) => post('/v1/admin/ciudades', d),
            recargar,
            { valores: { zonaHoraria: 'America/Mexico_City' } },
          ),
      }),
    ),
    tabla(
      [
        { titulo: 'Ciudad', valor: (c) => c.nombre },
        { titulo: 'Estado', valor: (c) => c.estado },
        { titulo: 'Zona horaria', valor: (c) => c.zonaHoraria },
      ],
      cat.ciudades,
    ),
    el('h2', { text: 'Categorías' }),
    el('div', { class: 'barra' },
      el('button', {
        type: 'button',
        class: 'primario',
        text: 'Agregar categoría',
        onclick: () =>
          enDialogo(
            'Nueva categoría',
            [
              { nombre: 'nombre', etiqueta: 'Nombre', requerido: true, largo: 60 },
              {
                nombre: 'clave',
                etiqueta: 'Clave',
                requerido: true,
                largo: 41,
                ayuda: 'Mayúsculas y guion bajo, por ejemplo MEDIO_AMBIENTE. La usa la app internamente.',
              },
              { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'area', largo: 300 },
              { nombre: 'activa', etiqueta: 'Activa', tipo: 'casilla', porDefecto: true },
            ],
            (d) => post('/v1/admin/categorias', d),
            recargar,
          ),
      }),
    ),
    tabla(
      [
        { titulo: 'Categoría', valor: (c) => c.nombre },
        { titulo: 'Clave', valor: (c) => el('span', { class: 'mono', text: c.clave }) },
        { titulo: 'Descripción', valor: (c) => c.descripcion || '' },
      ],
      cat.categorias,
    ),
  );
}

// ---------------- Niveles e insignias ----------------

async function reconocimientos({ recargar }) {
  const [niveles, insignias, cat] = await Promise.all([get('/v1/admin/niveles'), get('/v1/admin/insignias'), catalogos()]);
  return el(
    'div',
    {},
    encabezado('Niveles e insignias'),
    el('p', { class: 'nota', text: 'Las familias suben de nivel y ganan insignias según las actividades a las que asistieron (asistencia registrada por el equipo).' }),
    el('h2', { text: 'Niveles' }),
    el('div', { class: 'barra' },
      el('button', {
        type: 'button',
        class: 'primario',
        text: 'Agregar nivel',
        onclick: () =>
          enDialogo(
            'Nuevo nivel',
            [
              { nombre: 'nombre', etiqueta: 'Nombre', requerido: true, largo: 80 },
              { nombre: 'participacionesMinimas', etiqueta: 'Participaciones mínimas', tipo: 'entero', requerido: true, min: 0 },
              { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'area', largo: 500 },
            ],
            (d) => post('/v1/admin/niveles', d),
            recargar,
          ),
      }),
    ),
    tabla(
      [
        { titulo: 'Nivel', valor: (n) => n.nombre },
        { titulo: 'Desde', valor: (n) => `${n.participacionesMinimas} participaciones` },
        { titulo: 'Descripción', valor: (n) => n.descripcion || '' },
      ],
      niveles,
    ),
    el('h2', { text: 'Insignias' }),
    el('div', { class: 'barra' },
      el('button', {
        type: 'button',
        class: 'primario',
        text: 'Agregar insignia',
        onclick: () =>
          enDialogo(
            'Nueva insignia',
            [
              { nombre: 'nombre', etiqueta: 'Nombre', requerido: true, largo: 80 },
              { nombre: 'participacionesRequeridas', etiqueta: 'Participaciones requeridas', tipo: 'entero', requerido: true, min: 1 },
              {
                nombre: 'categoriaId',
                etiqueta: 'Categoría',
                tipo: 'select',
                opciones: cat.categorias.map((c) => ({ valor: c.id, texto: c.nombre })),
                vacio: 'Cualquier categoría',
              },
              { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'area', requerido: true, largo: 500 },
              { nombre: 'imagenClave', etiqueta: 'Imagen', tipo: 'imagen' },
            ],
            (d) => post('/v1/admin/insignias', d),
            recargar,
          ),
      }),
    ),
    tabla(
      [
        { titulo: 'Insignia', valor: (i) => i.nombre },
        { titulo: 'Requisito', valor: (i) => `${i.participacionesRequeridas} participaciones${i.categoria ? ` en ${i.categoria}` : ''}` },
        { titulo: 'Descripción', valor: (i) => i.descripcion || '' },
        { titulo: 'Activa', valor: (i) => siNo(i.activa) },
      ],
      insignias,
    ),
  );
}

// ---------------- Aviso de privacidad ----------------

async function privacidad({ recargar }) {
  const [avisos, cat] = await Promise.all([get('/v1/admin/avisos-privacidad'), catalogos(true)]);
  const vigente = cat.avisoPrivacidad;
  return el(
    'div',
    {},
    encabezado(
      'Aviso de privacidad',
      el('button', {
        type: 'button',
        class: 'primario',
        text: 'Publicar nueva versión',
        onclick: () =>
          enDialogo(
            'Nueva versión del aviso de privacidad',
            [
              { nombre: 'version', etiqueta: 'Versión', requerido: true, largo: 30, ayuda: 'Por ejemplo 2026-10. No se puede repetir.' },
              { nombre: 'contenido', etiqueta: 'Texto completo', tipo: 'area', requerido: true, largo: 100000, filas: 16 },
            ],
            (d) => post('/v1/admin/avisos-privacidad', d),
            recargar,
            { valores: { contenido: vigente ? vigente.contenido : '' }, textoBoton: 'Publicar' },
          ),
      }),
    ),
    el('p', {
      class: 'nota',
      text: 'Al publicar una versión nueva, cada persona tendrá que aceptarla la próxima vez que abra la app (LFPDPPP). Las versiones anteriores se conservan como evidencia.',
    }),
    tabla(
      [
        { titulo: 'Versión', valor: (a) => [a.version, vigente && vigente.id === a.id ? el('span', { class: 'chip bien', text: 'Vigente' }) : null] },
        { titulo: 'Publicada', valor: (a) => fechaHora(a.publicadoEn) },
        { titulo: 'Caracteres', valor: (a) => a.caracteres },
        { titulo: 'Aceptaciones', valor: (a) => a.aceptaciones },
      ],
      avisos,
      'Todavía no hay aviso publicado, nadie se puede registrar hasta que exista',
    ),
    vigente ? el('h2', { text: 'Texto vigente' }) : null,
    vigente ? el('div', { class: 'tarjeta texto-largo', text: vigente.contenido }) : null,
  );
}

// ---------------- Seguridad ----------------

/** Resume el user agent de un navegador en algo legible. Lo que no es navegador se deja igual. */
function describirAgente(ua) {
  if (!ua || !ua.startsWith('Mozilla/')) return ua || 'Dispositivo desconocido';
  const navegador = /Edg\//.test(ua)
    ? 'Edge'
    : /Firefox\//.test(ua)
      ? 'Firefox'
      : /Chrome\//.test(ua)
        ? 'Chrome'
        : /Safari\//.test(ua)
          ? 'Safari'
          : 'Navegador';
  const sistema = /Windows/.test(ua)
    ? 'Windows'
    : /Android/.test(ua)
      ? 'Android'
      : /iPhone|iPad/.test(ua)
        ? 'iOS'
        : /Mac OS X/.test(ua)
          ? 'macOS'
          : /Linux/.test(ua)
            ? 'Linux'
            : 'otro sistema';
  return `${navegador} en ${sistema}`;
}

function mostrarCodigos(codigos) {
  return el(
    'div',
    {},
    el('p', {
      class: 'nota',
      text: 'Guarda estos códigos de respaldo en un lugar seguro (por ejemplo un gestor de contraseñas). Cada uno sirve una sola vez si pierdes el teléfono. No se volverán a mostrar.',
    }),
    el('div', { class: 'codigos' }, codigos.map((c) => el('span', { text: c }))),
  );
}

function activarSegundoFactor(caja, ctx) {
  const pasoContrasena = () =>
    vaciar(
      caja,
      el('h2', { text: 'Activar el segundo factor' }),
      el('p', {
        text: 'Necesitas una app de autenticación en tu teléfono, por ejemplo Google Authenticator, Microsoft Authenticator, Aegis o 2FAS. Primero confirma tu contraseña.',
      }),
      formulario([{ nombre: 'password', etiqueta: 'Contraseña', tipo: 'contrasena', requerido: true, autocompletar: 'current-password' }], {
        textoBoton: 'Continuar',
        enviar: async (d) => pasoQr(await post('/v1/admin/2fa/iniciar', d)),
      }),
    );

  const pasoQr = (datos) => {
    const qr = el('img', { class: 'qr', alt: 'Código QR para la app de autenticación' });
    // El SVG lo genera la API, se muestra como imagen (no se inserta como HTML)
    qr.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(datos.qrSvg)}`;
    vaciar(
      caja,
      el('h2', { text: 'Escanea el código' }),
      el('p', { text: datos.instrucciones }),
      qr,
      el('p', {}, 'Si no puedes escanearlo, escribe esta clave en la app, ', el('span', { class: 'mono', text: datos.secreto })),
      formulario([{ nombre: 'codigo', etiqueta: 'Código de 6 dígitos que muestra la app', requerido: true, modo: 'numeric', autocompletar: 'one-time-code' }], {
        textoBoton: 'Activar',
        enviar: async (d) => {
          const r = await post('/v1/admin/2fa/confirmar', { codigo: d.codigo.replace(/\s/g, '') });
          await ctx.actualizarSesion();
          vaciar(
            caja,
            el('h2', { text: 'Segundo factor activado' }),
            el('p', { class: 'nota buena', text: 'Desde ahora, al entrar se te pedirá el código de la app. Se cerraron tus otras sesiones.' }),
            mostrarCodigos(r.codigosRespaldo),
            el('button', { type: 'button', class: 'primario', text: 'Ya los guardé, continuar', onclick: () => ctx.ir('#/inicio') }),
          );
        },
      }),
    );
  };

  pasoContrasena();
}

async function vistaSeguridad(ctx) {
  const { sesion, recargar } = ctx;
  const sf = sesion.segundoFactor;
  const contenido = el('div', {}, encabezado('Seguridad'));

  // Segundo factor
  const caja2fa = el('div', { class: 'tarjeta' });
  contenido.appendChild(caja2fa);
  if (!sf.activo) {
    if (sf.obligatorio) {
      contenido.insertBefore(
        el('p', { class: 'nota mala', text: 'Para usar el panel primero activa el segundo factor. Es obligatorio en este servidor para todas las cuentas de administración.' }),
        caja2fa,
      );
    }
    activarSegundoFactor(caja2fa, ctx);
  } else {
    vaciar(
      caja2fa,
      el('h2', { text: 'Segundo factor' }),
      ficha([
        ['Estado', chip('activo')],
        ['Activado', fechaHora(sf.activadoEn)],
        ['Códigos de respaldo sin usar', String(sf.codigosRespaldoRestantes)],
        ['Esta sesión', sesion.sesionConSegundoFactor ? 'Se abrió con código' : 'Se abrió sin código'],
      ]),
      sf.codigosRespaldoRestantes <= 3 ? el('p', { class: 'nota', text: 'Te quedan pocos códigos de respaldo, genera unos nuevos.' }) : null,
      el('h3', { text: 'Generar códigos de respaldo nuevos' }),
      el('p', { class: 'ayuda', text: 'Los anteriores dejan de servir.' }),
      formulario([{ nombre: 'codigo', etiqueta: 'Código actual de la app', requerido: true, modo: 'numeric', autocompletar: 'one-time-code' }], {
        textoBoton: 'Generar',
        enviar: async (d) => {
          const r = await post('/v1/admin/2fa/codigos-respaldo', { codigo: d.codigo.replace(/\s/g, '') });
          dialogo('Códigos de respaldo nuevos', mostrarCodigos(r.codigosRespaldo), { alCerrar: recargar });
        },
      }),
    );
  }

  // Sin segundo factor obligatorio pendiente, se muestra todo lo demás
  if (sf.obligatorio && !sesion.sesionConSegundoFactor) return contenido;

  const [sesiones, alertas, bitacora] = await Promise.all([
    get('/v1/yo/sesiones'),
    get('/v1/admin/alertas'),
    get(conFiltros('/v1/admin/bitacora', { limite: 50 })),
  ]);

  contenido.append(
    el('h2', { text: 'Mis sesiones abiertas' }),
    el('div', { class: 'barra' },
      botonAccion(
        'Cerrar todas las demás',
        async () => {
          await post('/v1/yo/sesiones/cerrar-otras');
          aviso('Se cerraron las demás sesiones');
          recargar();
        },
        { clase: '', confirmacion: '¿Cerrar todas las sesiones menos esta?' },
      ),
    ),
    tabla(
      [
        { titulo: 'Dispositivo', valor: (s) => [describirAgente(s.dispositivo), ' ', s.actual ? el('span', { class: 'chip bien', text: 'Esta' }) : null] },
        { titulo: 'Inició', valor: (s) => fechaHora(s.iniciada) },
        { titulo: 'Última actividad', valor: (s) => fechaHora(s.ultimaActividad) },
        { titulo: 'Con código', valor: (s) => siNo(s.segundoFactor) },
        {
          titulo: '',
          clase: 'acciones',
          valor: (s) =>
            s.actual
              ? ''
              : botonAccion('Cerrar', async () => {
                  await borrar(`/v1/yo/sesiones/${s.id}`);
                  aviso('Sesión cerrada');
                  recargar();
                }),
        },
      ],
      sesiones,
    ),
  );

  // Integridad de la bitácora
  const resultadoVerificar = el('div');
  contenido.append(
    el('h2', { text: 'Bitácora de seguridad' }),
    el('p', {
      class: 'ayuda',
      text: 'Cada registro está encadenado con el hash del anterior. Si alguien edita o borra uno, la verificación lo detecta. El ancla semanal llega por correo y sirve para comprobar que nadie reescribió la cadena completa.',
    }),
    el(
      'div',
      { class: 'barra' },
      botonAccion(
        'Verificar integridad',
        async () => {
          const r = await get('/v1/admin/bitacora/verificar');
          vaciar(
            resultadoVerificar,
            el('div', { class: `nota ${r.valida ? 'buena' : 'mala'}` },
              r.valida ? `Cadena íntegra, ${r.revisadas} registros revisados.` : `La cadena está alterada. Primer error en el registro ${r.primerError}.`,
            ),
          );
        },
        { clase: '' },
      ),
      el('button', {
        type: 'button',
        text: 'Comprobar contra un ancla',
        onclick: () => {
          let cerrar = null;
          const f = formulario(
            [
              { nombre: 'hastaId', etiqueta: 'Registro (hastaId del correo)', tipo: 'entero', requerido: true, min: 1 },
              { nombre: 'hash', etiqueta: 'Hash del correo', requerido: true, largo: 64 },
            ],
            {
              textoBoton: 'Comprobar',
              alCancelar: () => cerrar(),
              enviar: async (d) => {
                const r = await get(conFiltros('/v1/admin/bitacora/verificar', d));
                cerrar();
                vaciar(
                  resultadoVerificar,
                  el('div', { class: `nota ${r.valida ? 'buena' : 'mala'}` },
                    r.coincideAncla ? 'El ancla coincide, la bitácora no se reescribió desde ese correo.' : 'El ancla no coincide. La bitácora se modificó o el dato está mal escrito.',
                  ),
                );
              },
            },
          );
          cerrar = dialogo('Comprobar ancla', f);
        },
      }),
      botonAccion(
        'Enviar ancla ahora',
        async () => {
          await post('/v1/admin/bitacora/anclar');
          aviso('Ancla enviada a los correos de alertas');
        },
        { clase: '' },
      ),
    ),
    resultadoVerificar,
    tabla(
      [
        { titulo: 'Núm.', valor: (b) => b.id },
        { titulo: 'Fecha', valor: (b) => fechaHora(b.creadoEn) },
        { titulo: 'Acción', valor: (b) => el('span', { class: 'mono', text: b.accion }) },
        { titulo: 'Quién', valor: (b) => (b.actorUsername ? `@${b.actorUsername}` : b.actorRol || '') },
        { titulo: 'Ruta', valor: (b) => el('span', { class: 'mono', text: b.ruta || '' }) },
        { titulo: 'IP', valor: (b) => el('span', { class: 'mono', text: b.ip || '' }) },
      ],
      bitacora.eventos,
    ),
    el('h2', { text: 'Alertas enviadas' }),
    tabla(
      [
        { titulo: 'Fecha', valor: (a) => fechaHora(a.creadoEn) },
        { titulo: 'Regla', valor: (a) => el('span', { class: 'mono', text: a.regla }) },
        { titulo: 'Detalle', valor: (a) => el('div', { class: 'mono texto-largo', text: typeof a.detalle === 'string' ? a.detalle : JSON.stringify(a.detalle) }) },
        { titulo: 'Avisadas', valor: (a) => a.destinatarios },
      ],
      alertas,
      'Sin alertas',
    ),
  );
  return contenido;
}

export { vistaSeguridad };
export const vistasAjustes = { catalogos: catalogosVista, reconocimientos, privacidad };
