// Moderación y atención: propuestas, testimonios, reportes, entregas, calidad, personas y
// solicitudes de eliminación.

import { conFiltros, get, post, put } from '../api.js';
import {
  aviso,
  botonAccion,
  buscador,
  chip,
  dialogo,
  el,
  fechaHora,
  filtroSelect,
  formulario,
  siNo,
  tabla,
  vaciar,
} from '../ui.js';

const encabezado = (titulo, ...extra) => el('div', { class: 'encabezado' }, el('h1', { text: titulo }), el('div', {}, extra));

/** Listado con un filtro de estado arriba que vuelve a pedir los datos al cambiar. */
async function listadoConEstado({ titulo, ruta, estados, inicial, columnas, vacio, nota }) {
  const filtro = { estado: inicial };
  const resultados = el('div');
  const cargar = async () => {
    const lista = await get(conFiltros(ruta, filtro));
    vaciar(resultados, tabla(columnas(cargar), lista, vacio));
  };
  await cargar();
  return el(
    'div',
    {},
    encabezado(titulo),
    nota ? el('p', { class: 'nota', text: nota }) : null,
    el(
      'div',
      { class: 'barra' },
      filtroSelect(estados, inicial, (v) => {
        filtro.estado = v;
        cargar();
      }, 'Todos'),
    ),
    resultados,
  );
}

/** Diálogo con un formulario de estado y comentario, para revisar o atender algo. */
function revisar(titulo, campos, enviar, recargar) {
  let cerrar = null;
  const f = formulario(campos, {
    textoBoton: 'Guardar',
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

const imagen = (clave) => (clave ? el('a', { href: `/v1/archivos/${clave}`, target: '_blank', rel: 'noopener', text: 'Ver foto' }) : '');

// ---------------- Propuestas ----------------

const ESTADOS_PROPUESTA = [
  { valor: 'en_revision', texto: 'En revisión' },
  { valor: 'necesita_cambios', texto: 'Necesita cambios' },
  { valor: 'aprobada', texto: 'Aprobada' },
  { valor: 'rechazada', texto: 'Rechazada' },
  { valor: 'completada', texto: 'Completada' },
];

function propuestas() {
  return listadoConEstado({
    titulo: 'Propuestas de la comunidad',
    ruta: '/v1/admin/propuestas',
    estados: ESTADOS_PROPUESTA,
    inicial: 'en_revision',
    vacio: 'No hay propuestas con ese estado',
    nota: 'Quien propuso recibe una notificación en la app con el estado y tu comentario.',
    columnas: (recargar) => [
      { titulo: 'Propuesta', valor: (p) => [el('strong', { text: p.titulo }), el('div', { class: 'texto-largo', text: p.descripcion })] },
      { titulo: 'Tipo', valor: (p) => p.tipo },
      { titulo: 'Ubicación', valor: (p) => p.ubicacion || '' },
      {
        titulo: 'Contacto',
        valor: (p) => [p.autor, p.contactoNombre ? el('div', { text: p.contactoNombre }) : null, p.contactoCorreo ? el('div', { text: p.contactoCorreo }) : null, p.contactoTelefono ? el('div', { text: p.contactoTelefono }) : null],
      },
      { titulo: 'Fecha', valor: (p) => fechaHora(p.creadoEn) },
      { titulo: 'Estado', valor: (p) => [chip(p.estado), p.comentarioAdmin ? el('div', { class: 'ayuda', text: p.comentarioAdmin }) : null] },
      {
        titulo: '',
        clase: 'acciones',
        valor: (p) =>
          el('button', {
            type: 'button',
            class: 'chico',
            text: 'Revisar',
            onclick: () =>
              revisar(
                `Revisar ${p.titulo}`,
                [
                  { nombre: 'estado', etiqueta: 'Nuevo estado', tipo: 'select', requerido: true, opciones: ESTADOS_PROPUESTA.slice(1) },
                  { nombre: 'comentario', etiqueta: 'Comentario para quien propuso', tipo: 'area', largo: 2000 },
                ],
                (d) => put(`/v1/admin/propuestas/${p.id}/revision`, d),
                recargar,
              ),
          }),
      },
    ],
  });
}

// ---------------- Testimonios ----------------

function testimonios() {
  return listadoConEstado({
    titulo: 'Testimonios',
    ruta: '/v1/admin/testimonios',
    estados: [
      { valor: 'pendiente', texto: 'Pendientes' },
      { valor: 'aprobado', texto: 'Aprobados' },
      { valor: 'rechazado', texto: 'Rechazados' },
    ],
    inicial: 'pendiente',
    vacio: 'No hay testimonios con ese estado',
    nota: 'Solo los testimonios aprobados aparecen en la app, y solo para las familias de la misma ciudad.',
    columnas: (recargar) => [
      { titulo: 'Testimonio', valor: (t) => el('div', { class: 'texto-largo', text: t.texto }) },
      { titulo: 'Actividad', valor: (t) => t.actividad },
      { titulo: 'Autor', valor: (t) => t.autor },
      { titulo: 'Foto', valor: (t) => imagen(t.fotoClave) },
      { titulo: 'Estado', valor: (t) => chip(t.estado) },
      {
        titulo: '',
        clase: 'acciones',
        valor: (t) =>
          t.estado !== 'pendiente'
            ? ''
            : [
                botonAccion('Aprobar', async () => {
                  await put(`/v1/admin/testimonios/${t.id}`, { estado: 'aprobado' });
                  aviso('Testimonio aprobado');
                  recargar();
                }),
                el('button', {
                  type: 'button',
                  class: 'chico peligro',
                  text: 'Rechazar',
                  onclick: () =>
                    revisar(
                      'Rechazar testimonio',
                      [{ nombre: 'comentario', etiqueta: 'Motivo (opcional, lo verá la familia)', tipo: 'area', largo: 1000 }],
                      (d) => put(`/v1/admin/testimonios/${t.id}`, { estado: 'rechazado', ...d }),
                      recargar,
                    ),
                }),
              ],
      },
    ],
  });
}

// ---------------- Reportes ----------------

function reportes() {
  return listadoConEstado({
    titulo: 'Reportes de experiencia',
    ruta: '/v1/admin/reportes',
    estados: [
      { valor: 'pendiente', texto: 'Pendientes' },
      { valor: 'en_revision', texto: 'En revisión' },
      { valor: 'resuelto', texto: 'Resueltos' },
    ],
    inicial: 'pendiente',
    vacio: 'No hay reportes con ese estado',
    columnas: (recargar) => [
      { titulo: 'Reporte', valor: (r) => [el('strong', { text: r.tipo }), el('div', { class: 'texto-largo', text: r.descripcion })] },
      { titulo: 'Satisfacción', valor: (r) => (r.nivelSatisfaccion ? `${r.nivelSatisfaccion} de 5` : '') },
      {
        titulo: 'Sobre',
        valor: (r) =>
          r.actividadId
            ? el('a', { href: `#/actividades/${r.actividadId}`, text: 'Actividad' })
            : r.asociacionId
              ? el('a', { href: `#/asociaciones/${r.asociacionId}`, text: 'Asociación' })
              : r.campanaId
                ? 'Campaña'
                : '',
      },
      { titulo: 'Autor', valor: (r) => r.autor },
      { titulo: 'Foto', valor: (r) => imagen(r.fotoClave) },
      { titulo: 'Fecha', valor: (r) => fechaHora(r.creadoEn) },
      { titulo: 'Estado', valor: (r) => chip(r.estado) },
      {
        titulo: '',
        clase: 'acciones',
        valor: (r) =>
          r.estado === 'resuelto'
            ? ''
            : el('button', {
                type: 'button',
                class: 'chico',
                text: 'Atender',
                onclick: () =>
                  revisar(
                    'Atender reporte',
                    [
                      {
                        nombre: 'estado',
                        etiqueta: 'Estado',
                        tipo: 'select',
                        requerido: true,
                        opciones: [
                          { valor: 'en_revision', texto: 'En revisión' },
                          { valor: 'resuelto', texto: 'Resuelto' },
                        ],
                      },
                      { nombre: 'respuesta', etiqueta: 'Respuesta para la familia', tipo: 'area', largo: 2000 },
                    ],
                    (d) => put(`/v1/admin/reportes/${r.id}`, d),
                    recargar,
                  ),
              }),
      },
    ],
  });
}

// ---------------- Entregas ----------------

function entregas() {
  return listadoConEstado({
    titulo: 'Entregas de donativos',
    ruta: '/v1/admin/entregas',
    estados: [
      { valor: 'registrada', texto: 'Por confirmar' },
      { valor: 'recibida', texto: 'Recibidas' },
      { valor: 'cancelada', texto: 'Canceladas' },
    ],
    inicial: 'registrada',
    vacio: 'No hay entregas con ese estado',
    nota: 'Confirma una entrega solo cuando la asociación o el punto de entrega te confirme que la recibió. Al confirmarla se suma al avance de la campaña.',
    columnas: (recargar) => [
      { titulo: 'Campaña', valor: (e) => e.campana },
      { titulo: 'Artículo', valor: (e) => `${e.cantidad} ${e.unidad} de ${e.articulo}` },
      { titulo: 'Punto de entrega', valor: (e) => e.puntoEntrega },
      { titulo: 'Donante', valor: (e) => e.donante },
      { titulo: 'Comentario', valor: (e) => el('div', { class: 'texto-largo', text: e.comentario || '' }) },
      { titulo: 'Fecha', valor: (e) => fechaHora(e.creadoEn) },
      { titulo: 'Estado', valor: (e) => chip(e.estado) },
      {
        titulo: '',
        clase: 'acciones',
        valor: (e) =>
          e.estado !== 'registrada'
            ? ''
            : [
                botonAccion('Recibida', async () => {
                  await put(`/v1/admin/entregas/${e.id}`, { estado: 'recibida' });
                  aviso('Entrega confirmada');
                  recargar();
                }),
                botonAccion(
                  'Cancelar',
                  async () => {
                    await put(`/v1/admin/entregas/${e.id}`, { estado: 'cancelada' });
                    aviso('Entrega cancelada');
                    recargar();
                  },
                  { peligro: true, confirmacion: '¿Cancelar esta entrega? La familia verá que no se recibió.' },
                ),
              ],
      },
    ],
  });
}

// ---------------- Calidad ----------------

async function calidad() {
  const lista = await get('/v1/admin/calidad');
  return el(
    'div',
    {},
    encabezado('Calidad de asociaciones'),
    el('p', {
      class: 'nota',
      text: 'La calidad combina los me gusta y no me gusta de quienes asistieron a sus actividades. Las de calidad más baja y con más reportes aparecen primero.',
    }),
    tabla(
      [
        { titulo: 'Asociación', valor: (a) => el('a', { href: `#/asociaciones/${a.id}`, text: a.nombre }) },
        { titulo: 'Me gusta', valor: (a) => a.meGusta },
        { titulo: 'No me gusta', valor: (a) => a.noMeGusta },
        { titulo: 'Calidad', valor: (a) => (a.calidad === null ? 'Sin votos' : `${Math.round(a.calidad * 100)}%`) },
        { titulo: 'Reportes', valor: (a) => a.reportes },
        { titulo: 'Verificada', valor: (a) => siNo(a.verificada) },
        { titulo: 'Activa', valor: (a) => siNo(a.activa) },
      ],
      lista,
    ),
  );
}

// ---------------- Personas ----------------

async function usuarios({ sesion }) {
  const filtro = { q: '', rol: '', estado: '' };
  const resultados = el('div');
  const cargar = async () => {
    const lista = await get(conFiltros('/v1/admin/usuarios', { ...filtro, limite: 50 }));
    vaciar(
      resultados,
      tabla(
        [
          { titulo: 'Nombre', valor: (u) => [u.nombre, el('div', { class: 'ayuda', text: `@${u.username}` })] },
          { titulo: 'Contacto', valor: (u) => [u.correo || '', u.telefono ? el('div', { text: u.telefono }) : null] },
          { titulo: 'Ciudad', valor: (u) => u.ciudad || '' },
          { titulo: 'Rol', valor: (u) => (u.rol === 'admin' ? 'Administración' : 'Familia') },
          { titulo: 'Último acceso', valor: (u) => fechaHora(u.ultimoAcceso) },
          { titulo: 'Estado', valor: (u) => chip(u.estado) },
          {
            titulo: '',
            clase: 'acciones',
            valor: (u) =>
              u.id === sesion.usuario.id || u.estado === 'pendiente_eliminacion'
                ? ''
                : u.estado === 'activo'
                  ? botonAccion(
                      'Suspender',
                      async () => {
                        await put(`/v1/admin/usuarios/${u.id}/estado`, { estado: 'suspendido' });
                        aviso('Cuenta suspendida, sus sesiones se cerraron');
                        cargar();
                      },
                      { peligro: true, confirmacion: `¿Suspender la cuenta de ${u.nombre}? Se cierran todas sus sesiones al instante.` },
                    )
                  : botonAccion('Reactivar', async () => {
                      await put(`/v1/admin/usuarios/${u.id}/estado`, { estado: 'activo' });
                      aviso('Cuenta reactivada');
                      cargar();
                    }),
          },
        ],
        lista,
        'No hay cuentas con esos filtros',
      ),
    );
  };
  await cargar();
  return el(
    'div',
    {},
    encabezado('Personas'),
    el(
      'div',
      { class: 'barra' },
      buscador('', (v) => {
        filtro.q = v;
        cargar();
      }, 'Nombre, usuario, correo o teléfono'),
      filtroSelect(
        [
          { valor: 'familia', texto: 'Familias' },
          { valor: 'admin', texto: 'Administración' },
        ],
        '',
        (v) => {
          filtro.rol = v;
          cargar();
        },
        'Todos los roles',
      ),
      filtroSelect(
        [
          { valor: 'activo', texto: 'Activas' },
          { valor: 'suspendido', texto: 'Suspendidas' },
          { valor: 'pendiente_eliminacion', texto: 'Por eliminar' },
        ],
        '',
        (v) => {
          filtro.estado = v;
          cargar();
        },
        'Todos los estados',
      ),
    ),
    el('p', { class: 'ayuda', text: 'Se muestran las 50 más recientes que coinciden. Usa la búsqueda para encontrar a alguien.' }),
    resultados,
  );
}

// ---------------- Solicitudes de eliminación ----------------

async function solicitudes({ recargar }) {
  const lista = await get('/v1/admin/solicitudes-eliminacion');
  return el(
    'div',
    {},
    encabezado('Solicitudes de eliminación'),
    el('p', {
      class: 'nota',
      text: 'Derecho de cancelación (ARCO). Al resolver se anonimizan los datos de la persona y se borran sus fotos. No se puede deshacer. Las solicitudes por inactividad las genera el sistema tras avisar por correo.',
    }),
    tabla(
      [
        { titulo: 'Persona', valor: (s) => s.nombre },
        { titulo: 'Correo', valor: (s) => s.correo || '' },
        { titulo: 'Solicitada', valor: (s) => fechaHora(s.solicitadaEn) },
        { titulo: 'Estado', valor: (s) => chip(s.estado) },
        {
          titulo: '',
          clase: 'acciones',
          valor: (s) =>
            botonAccion(
              'Resolver y anonimizar',
              async () => {
                const r = await post(`/v1/admin/solicitudes-eliminacion/${s.id}/resolver`);
                aviso(`Datos anonimizados. ${r.archivosEliminados} archivos borrados.`);
                recargar();
              },
              { peligro: true, confirmacion: `Se anonimizarán los datos de ${s.nombre} y se borrarán sus fotos. Esta acción no se puede deshacer.` },
            ),
        },
      ],
      lista,
      'No hay solicitudes pendientes',
    ),
  );
}

export const vistasComunidad = { propuestas, testimonios, reportes, entregas, calidad, usuarios, solicitudes };
