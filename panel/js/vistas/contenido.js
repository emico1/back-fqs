// Inicio, asociaciones, actividades (con participantes y encuestas), proyectos y campañas.

import { catalogos, conFiltros, get, post, put, todas } from '../api.js';
import {
  aviso,
  barraAvance,
  botonAccion,
  buscador,
  chip,
  dialogo,
  el,
  fecha,
  fechaHora,
  filtroSelect,
  formulario,
  siNo,
  tabla,
  vaciar,
} from '../ui.js';

const opcionesCiudad = (cat) => cat.ciudades.map((c) => ({ valor: c.id, texto: `${c.nombre}, ${c.estado}` }));
const opcionesCategoria = (cat) => cat.categorias.map((c) => ({ valor: c.id, texto: c.nombre }));
const opcionesAsociacion = (lista) => lista.map((a) => ({ valor: a.id, texto: a.nombre + (a.verificada ? '' : ' (sin verificar)') }));

function encabezado(titulo, ...acciones) {
  return el('div', { class: 'encabezado' }, el('h1', { text: titulo }), el('div', {}, acciones));
}
const enlaceBoton = (href, texto, primario = true) => el('a', { href, class: `boton ${primario ? 'primario' : ''}`, text: texto });

// ---------------- Inicio ----------------

async function inicio() {
  const r = await get('/v1/admin/resumen');
  const cifra = (n, etiqueta, href) =>
    el('a', { class: `cifra ${n > 0 ? 'pendiente' : ''}`, href }, el('div', { class: 'numero', text: n }), el('div', { class: 'etiqueta', text: etiqueta }));
  return el(
    'div',
    {},
    el('h1', { text: 'Inicio' }),
    el('h2', { text: 'Pendientes' }),
    el(
      'div',
      { class: 'cifras' },
      cifra(r.propuestasPorRevisar, 'Propuestas por revisar', '#/propuestas'),
      cifra(r.testimoniosPorModerar, 'Testimonios por moderar', '#/testimonios'),
      cifra(r.reportesAbiertos, 'Reportes abiertos', '#/reportes'),
      cifra(r.entregasPorConfirmar, 'Entregas por confirmar', '#/entregas'),
      cifra(r.solicitudesEliminacion, 'Solicitudes de eliminación', '#/solicitudes'),
      cifra(r.asociacionesSinVerificar, 'Asociaciones sin verificar', '#/asociaciones'),
      cifra(r.actividadesBorrador, 'Actividades en borrador', '#/actividades'),
      cifra(r.alertasSemana, 'Alertas de seguridad en 7 días', '#/seguridad'),
    ),
    el('h2', { text: 'Comunidad' }),
    el(
      'div',
      { class: 'cifras' },
      cifra(r.familiasActivas, 'Cuentas de familia activas', '#/usuarios'),
      cifra(r.actividadesProximas, 'Actividades próximas publicadas', '#/actividades'),
    ),
    el('h2', { text: 'Próximas actividades' }),
    tabla(
      [
        { titulo: 'Actividad', valor: (a) => el('a', { href: `#/actividades/${a.id}`, text: a.titulo }) },
        { titulo: 'Asociación', valor: (a) => a.asociacion },
        { titulo: 'Fecha', valor: (a) => fechaHora(a.inicio) },
        { titulo: 'Cupo', valor: (a) => `${a.cuposOcupados} de ${a.cupoTotal}` },
      ],
      r.proximas,
      'No hay actividades próximas',
    ),
  );
}

// ---------------- Asociaciones ----------------

function camposAsociacion(cat) {
  return [
    { nombre: 'nombre', etiqueta: 'Nombre', requerido: true, largo: 150 },
    { nombre: 'categoriaId', etiqueta: 'Categoría', tipo: 'select', requerido: true, opciones: opcionesCategoria(cat) },
    { nombre: 'ciudadId', etiqueta: 'Ciudad', tipo: 'select', requerido: true, opciones: opcionesCiudad(cat) },
    { nombre: 'direccion', etiqueta: 'Dirección', requerido: true, largo: 300 },
    { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'area', requerido: true, largo: 2000 },
    { nombre: 'mision', etiqueta: 'Misión', tipo: 'area', largo: 3000 },
    { nombre: 'necesidades', etiqueta: 'Necesidades', tipo: 'area', largo: 3000 },
    { nombre: 'familiasBeneficiadas', etiqueta: 'Familias beneficiadas', tipo: 'entero', min: 0 },
    { nombre: 'telefono', etiqueta: 'Teléfono', tipo: 'tel' },
    { nombre: 'whatsapp', etiqueta: 'WhatsApp', tipo: 'tel' },
    { nombre: 'correo', etiqueta: 'Correo', tipo: 'correo' },
    { nombre: 'sitioWeb', etiqueta: 'Sitio web', tipo: 'url', ayuda: 'Debe empezar con https://' },
    { nombre: 'latitud', etiqueta: 'Latitud', tipo: 'numero', min: -90, max: 90 },
    { nombre: 'longitud', etiqueta: 'Longitud', tipo: 'numero', min: -180, max: 180 },
    { nombre: 'fotoClave', etiqueta: 'Foto', tipo: 'imagen' },
    { nombre: 'verificada', etiqueta: 'Verificada (las familias solo ven asociaciones verificadas)', tipo: 'casilla' },
    { nombre: 'activa', etiqueta: 'Activa', tipo: 'casilla', porDefecto: true },
  ];
}

async function asociaciones({ params, ir }) {
  const cat = await catalogos();
  if (params[0] === 'nueva') {
    return el(
      'div',
      {},
      encabezado('Nueva asociación'),
      el(
        'div',
        { class: 'tarjeta' },
        formulario(camposAsociacion(cat), {
          textoBoton: 'Crear asociación',
          alCancelar: () => ir('#/asociaciones'),
          enviar: async (d) => {
            await post('/v1/admin/asociaciones', d);
            aviso('Asociación creada');
            ir('#/asociaciones');
          },
        }),
      ),
    );
  }
  if (params[0]) {
    const a = await get(`/v1/admin/asociaciones/${encodeURIComponent(params[0])}`);
    return el(
      'div',
      {},
      encabezado(a.nombre, enlaceBoton(`#/actividades?asociacion=${a.id}`, 'Ver sus actividades', false)),
      el(
        'div',
        { class: 'tarjeta' },
        formulario(camposAsociacion(cat), {
          valores: a,
          alCancelar: () => ir('#/asociaciones'),
          enviar: async (d) => {
            await put(`/v1/admin/asociaciones/${a.id}`, d);
            aviso('Cambios guardados');
            ir('#/asociaciones');
          },
        }),
      ),
    );
  }

  const estado = { q: '', ciudadId: '' };
  const resultados = el('div');
  const cargar = async () => {
    const lista = await todas('/v1/admin/asociaciones', estado, 500);
    vaciar(
      resultados,
      tabla(
        [
          { titulo: 'Nombre', valor: (a) => el('a', { href: `#/asociaciones/${a.id}`, text: a.nombre }) },
          { titulo: 'Ciudad', valor: (a) => a.ciudad },
          { titulo: 'Categoría', valor: (a) => a.categoria },
          { titulo: 'Verificada', valor: (a) => siNo(a.verificada) },
          { titulo: 'Activa', valor: (a) => siNo(a.activa) },
          { titulo: 'Actividades publicadas', valor: (a) => a.actividadesPublicadas },
        ],
        lista,
        'No hay asociaciones con esos filtros',
      ),
    );
  };
  await cargar();
  return el(
    'div',
    {},
    encabezado('Asociaciones', enlaceBoton('#/asociaciones/nueva', 'Nueva asociación')),
    el(
      'div',
      { class: 'barra' },
      buscador('', (v) => {
        estado.q = v;
        cargar();
      }, 'Buscar por nombre'),
      filtroSelect(opcionesCiudad(cat), '', (v) => {
        estado.ciudadId = v;
        cargar();
      }, 'Todas las ciudades'),
    ),
    resultados,
  );
}

// ---------------- Actividades ----------------

function camposActividad(cat, asociacionesLista) {
  return [
    { nombre: 'titulo', etiqueta: 'Título', requerido: true, largo: 150 },
    { nombre: 'asociacionId', etiqueta: 'Asociación', tipo: 'select', requerido: true, opciones: opcionesAsociacion(asociacionesLista) },
    {
      nombre: 'tipo',
      etiqueta: 'Tipo',
      tipo: 'select',
      requerido: true,
      opciones: [
        { valor: 'voluntariado', texto: 'Voluntariado (Participar)' },
        { valor: 'visita', texto: 'Visita (Visiteo)' },
      ],
    },
    { nombre: 'categoriaId', etiqueta: 'Categoría', tipo: 'select', requerido: true, opciones: opcionesCategoria(cat) },
    { nombre: 'ciudadId', etiqueta: 'Ciudad', tipo: 'select', requerido: true, opciones: opcionesCiudad(cat) },
    { nombre: 'inicio', etiqueta: 'Inicio', tipo: 'fechahora', requerido: true },
    { nombre: 'fin', etiqueta: 'Fin', tipo: 'fechahora', requerido: true },
    { nombre: 'cupoTotal', etiqueta: 'Cupo total', tipo: 'entero', requerido: true, min: 1 },
    { nombre: 'edadMinima', etiqueta: 'Edad mínima', tipo: 'entero', min: 0, max: 120 },
    { nombre: 'aptaNinos', etiqueta: 'Apta para niñas y niños', tipo: 'casilla' },
    { nombre: 'direccion', etiqueta: 'Dirección', requerido: true, largo: 300, ancho: true },
    { nombre: 'latitud', etiqueta: 'Latitud', tipo: 'numero', min: -90, max: 90 },
    { nombre: 'longitud', etiqueta: 'Longitud', tipo: 'numero', min: -180, max: 180 },
    { nombre: 'descripcionCorta', etiqueta: 'Descripción corta', requerido: true, largo: 200, ancho: true },
    { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'area', requerido: true, largo: 5000 },
    { nombre: 'recomendaciones', etiqueta: 'Recomendaciones', tipo: 'area', largo: 2000 },
    { nombre: 'fotoClave', etiqueta: 'Foto', tipo: 'imagen' },
  ];
}

const ESTADOS_ACTIVIDAD = [
  { valor: 'borrador', texto: 'Borrador' },
  { valor: 'publicada', texto: 'Publicada' },
  { valor: 'finalizada', texto: 'Finalizada' },
  { valor: 'cancelada', texto: 'Cancelada' },
];

async function actividades({ params, ir, recargar }) {
  const cat = await catalogos();
  if (params[0] === 'nueva') {
    const lista = await todas('/v1/admin/asociaciones', {}, 500);
    return el(
      'div',
      {},
      encabezado('Nueva actividad'),
      el('p', { class: 'nota', text: 'La actividad se crea como borrador. Publícala cuando esté lista para que la vean las familias.' }),
      el(
        'div',
        { class: 'tarjeta' },
        formulario(camposActividad(cat, lista), {
          valores: { tipo: 'voluntariado' },
          textoBoton: 'Crear actividad',
          alCancelar: () => ir('#/actividades'),
          enviar: async (d) => {
            const r = await post('/v1/admin/actividades', d);
            aviso('Actividad creada');
            ir(`#/actividades/${r.id}`);
          },
        }),
      ),
    );
  }
  if (params[0]) return fichaActividad(params[0], cat, { ir, recargar });

  const filtroInicial = new URLSearchParams(location.hash.split('?')[1] || '');
  const estado = { q: '', estado: '', asociacionId: filtroInicial.get('asociacion') || '' };
  const resultados = el('div');
  let desplazamiento = 0;
  const cargar = async (mas = false) => {
    desplazamiento = mas ? desplazamiento + 50 : 0;
    const lista = await get(conFiltros('/v1/admin/actividades', { ...estado, limite: 50, desplazamiento }));
    const t = tabla(
      [
        { titulo: 'Actividad', valor: (a) => el('a', { href: `#/actividades/${a.id}`, text: a.titulo }) },
        { titulo: 'Asociación', valor: (a) => a.asociacion },
        { titulo: 'Inicio', valor: (a) => fechaHora(a.inicio) },
        { titulo: 'Tipo', valor: (a) => (a.tipo === 'visita' ? 'Visita' : 'Voluntariado') },
        { titulo: 'Cupo', valor: (a) => `${a.cuposOcupados} de ${a.cupoTotal}` },
        { titulo: 'Estado', valor: (a) => chip(a.estado) },
      ],
      lista,
      'No hay actividades con esos filtros',
    );
    if (mas) resultados.querySelector('.mas')?.remove();
    if (!mas) vaciar(resultados);
    resultados.appendChild(t);
    if (lista.length === 50) resultados.appendChild(el('div', { class: 'mas' }, botonAccion('Cargar más', () => cargar(true))));
  };
  await cargar();
  return el(
    'div',
    {},
    encabezado('Actividades', enlaceBoton('#/actividades/nueva', 'Nueva actividad')),
    el(
      'div',
      { class: 'barra' },
      buscador('', (v) => {
        estado.q = v;
        cargar();
      }, 'Buscar por título o asociación'),
      filtroSelect(ESTADOS_ACTIVIDAD, '', (v) => {
        estado.estado = v;
        cargar();
      }, 'Todos los estados'),
      estado.asociacionId ? el('a', { href: '#/actividades', class: 'boton', text: 'Quitar filtro de asociación' }) : null,
    ),
    resultados,
  );
}

async function fichaActividad(id, cat, { ir, recargar }) {
  const [a, lista, participantes, encuestas] = await Promise.all([
    get(`/v1/admin/actividades/${encodeURIComponent(id)}`),
    todas('/v1/admin/asociaciones', {}, 500),
    get(`/v1/admin/actividades/${encodeURIComponent(id)}/participantes`),
    get(`/v1/admin/actividades/${encodeURIComponent(id)}/encuestas`),
  ]);
  const cancelada = a.estado === 'cancelada';

  const cambiarEstado = (nuevo, texto) =>
    botonAccion(texto, async () => {
      await post(`/v1/admin/actividades/${a.id}/estado`, { estado: nuevo });
      aviso('Estado actualizado');
      recargar();
    });

  const cancelar = () =>
    dialogo(
      'Cancelar actividad',
      el(
        'div',
        {},
        el('p', {
          text: 'Se cancelan todas las inscripciones, se avisa a las familias en la app y a los acompañantes adultos con correo. No se puede deshacer.',
        }),
        formulario([{ nombre: 'motivo', etiqueta: 'Motivo (lo verán las familias)', tipo: 'area', requerido: true, largo: 500 }], {
          textoBoton: 'Cancelar actividad',
          enviar: async (d) => {
            const r = await post(`/v1/admin/actividades/${a.id}/cancelar`, d);
            document.querySelector('dialog')?.close();
            document.querySelector('dialog')?.remove();
            aviso(`Actividad cancelada. ${r.inscripcionesCanceladas} inscripciones canceladas.`);
            recargar();
          },
        }),
      ),
    );

  const asistencia = (p) =>
    p.estadoInscripcion !== 'confirmada'
      ? chip(p.estadoInscripcion)
      : filtroSelect(
          [
            { valor: 'pendiente', texto: 'Pendiente' },
            { valor: 'asistio', texto: 'Asistió' },
            { valor: 'no_asistio', texto: 'No asistió' },
          ],
          p.estadoAsistencia,
          async (v) => {
            try {
              await put(`/v1/admin/participantes/${p.id}/asistencia`, { estado: v });
              aviso('Asistencia registrada');
            } catch (e) {
              aviso(e.message, 'error');
            }
          },
          'Pendiente',
        );

  const confirmados = participantes.filter((p) => p.estadoInscripcion === 'confirmada');
  return el(
    'div',
    {},
    encabezado(
      a.titulo,
      chip(a.estado),
      ' ',
      !cancelada && a.estado !== 'publicada' ? cambiarEstado('publicada', 'Publicar') : null,
      !cancelada && a.estado === 'publicada' ? cambiarEstado('borrador', 'Volver a borrador') : null,
      !cancelada && a.estado !== 'finalizada' ? cambiarEstado('finalizada', 'Marcar finalizada') : null,
      !cancelada ? el('button', { type: 'button', class: 'chico peligro', text: 'Cancelar actividad', onclick: cancelar }) : null,
    ),
    cancelada ? el('p', { class: 'nota mala', text: `Cancelada. Motivo, ${a.motivoCancelacion || 'sin motivo'}` }) : null,
    el('h2', { text: `Participantes (${confirmados.length} personas confirmadas)` }),
    tabla(
      [
        { titulo: 'Persona', valor: (p) => [p.nombre, p.esTitular ? el('span', { class: 'chip neutro', text: 'Titular' }) : null] },
        { titulo: 'Edad', valor: (p) => p.edadAlEvento },
        { titulo: 'Familia', valor: (p) => p.titularNombre },
        { titulo: 'Contacto', valor: (p) => [p.titularTelefono || '', p.titularCorreo ? el('div', { text: p.titularCorreo }) : null] },
        { titulo: 'Asistencia', valor: asistencia },
      ],
      participantes,
      'Nadie se ha inscrito todavía',
    ),
    el('h2', { text: 'Encuestas' }),
    tabla(
      [
        { titulo: 'Encuesta', valor: (e) => el('a', { href: `#/encuestas/${e.id}`, text: e.titulo }) },
        { titulo: 'Momento', valor: (e) => (e.momento === 'antes' ? 'Antes' : 'Después') },
        { titulo: 'Respuestas', valor: (e) => `${e.respondieron} de ${e.inscritas}` },
        { titulo: 'Activa', valor: (e) => siNo(e.activa) },
      ],
      encuestas,
      'Sin encuestas',
    ),
    el('div', { class: 'barra' }, el('a', { href: `#/encuestas/nueva/${a.id}`, class: 'boton', text: 'Nueva encuesta' })),
    el('h2', { text: 'Datos de la actividad' }),
    el(
      'div',
      { class: 'tarjeta' },
      formulario(camposActividad(cat, lista), {
        valores: a,
        enviar: async (d) => {
          await put(`/v1/admin/actividades/${a.id}`, d);
          aviso('Cambios guardados');
          recargar();
        },
        alCancelar: () => ir('#/actividades'),
      }),
    ),
  );
}

// ---------------- Encuestas ----------------

async function encuestas({ params, ir, recargar }) {
  if (params[0] === 'nueva') {
    const actividadId = params[1];
    const a = await get(`/v1/admin/actividades/${encodeURIComponent(actividadId)}`);
    return el(
      'div',
      {},
      encabezado(`Nueva encuesta para ${a.titulo}`),
      el(
        'div',
        { class: 'tarjeta' },
        formulario(
          [
            { nombre: 'titulo', etiqueta: 'Título', requerido: true, largo: 150 },
            {
              nombre: 'momento',
              etiqueta: 'Cuándo se responde',
              tipo: 'select',
              requerido: true,
              opciones: [
                { valor: 'antes', texto: 'Antes de la actividad' },
                { valor: 'despues', texto: 'Después de la actividad' },
              ],
            },
            {
              nombre: 'preguntas',
              etiqueta: 'Preguntas',
              tipo: 'lista',
              minimo: 1,
              textoAgregar: 'Agregar pregunta',
              campos: [
                { nombre: 'texto', etiqueta: 'Pregunta', requerido: true, largo: 500, ancho: true },
                {
                  nombre: 'tipo',
                  etiqueta: 'Tipo',
                  tipo: 'select',
                  requerido: true,
                  porDefecto: 'opcion_unica',
                  opciones: [
                    { valor: 'opcion_unica', texto: 'Opción única' },
                    { valor: 'texto', texto: 'Respuesta abierta' },
                  ],
                },
                { nombre: 'obligatoria', etiqueta: 'Obligatoria', tipo: 'casilla', porDefecto: true },
                { nombre: 'opciones', etiqueta: 'Opciones', tipo: 'lineas', ayuda: 'Solo para opción única, una por renglón, mínimo 2' },
              ],
            },
          ],
          {
            valores: { momento: 'despues' },
            textoBoton: 'Crear encuesta',
            alCancelar: () => ir(`#/actividades/${a.id}`),
            enviar: async (d) => {
              d.actividadId = a.id;
              d.preguntas = d.preguntas.map((p) => ({ ...p, opciones: p.tipo === 'texto' ? [] : p.opciones || [] }));
              await post('/v1/admin/encuestas', d);
              aviso('Encuesta creada');
              ir(`#/actividades/${a.id}`);
            },
          },
        ),
      ),
    );
  }

  const r = await get(`/v1/admin/encuestas/${encodeURIComponent(params[0])}/resultados`);
  return el(
    'div',
    {},
    encabezado(
      r.titulo,
      siNo(r.activa, 'Activa', 'Cerrada'),
      ' ',
      botonAccion(r.activa ? 'Cerrar encuesta' : 'Reabrir encuesta', async () => {
        await post(`/v1/admin/encuestas/${r.id}/estado`, { activa: !r.activa });
        recargar();
      }),
    ),
    el('p', {}, 'Actividad, ', el('a', { href: `#/actividades/${r.actividadId}`, text: r.actividad })),
    r.preguntas.map((p) =>
      el(
        'div',
        { class: 'tarjeta' },
        el('h3', { text: p.texto }),
        el('p', { class: 'ayuda', text: `${p.respuestas} respuestas` }),
        p.tipo === 'opcion_unica'
          ? tabla(
              [
                { titulo: 'Opción', valor: (o) => o.texto },
                { titulo: 'Votos', valor: (o) => o.total },
                { titulo: '', valor: (o) => barraAvance(p.respuestas ? Math.round((o.total / p.respuestas) * 100) : 0) },
              ],
              p.opciones,
            )
          : p.textos.length
            ? el('ul', {}, p.textos.map((t) => el('li', { class: 'texto-largo', text: t })))
            : el('p', { class: 'vacio', text: 'Sin respuestas' }),
      ),
    ),
  );
}

// ---------------- Proyectos ----------------

function camposProyecto(cat, asociacionesLista) {
  return [
    { nombre: 'titulo', etiqueta: 'Título', requerido: true, largo: 150 },
    { nombre: 'asociacionId', etiqueta: 'Asociación', tipo: 'select', opciones: opcionesAsociacion(asociacionesLista), vacio: 'Sin asociación' },
    { nombre: 'ciudadId', etiqueta: 'Ciudad', tipo: 'select', requerido: true, opciones: opcionesCiudad(cat) },
    { nombre: 'fechaInicio', etiqueta: 'Fecha de inicio', tipo: 'fecha', requerido: true },
    { nombre: 'fechaFin', etiqueta: 'Fecha de fin', tipo: 'fecha' },
    { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'area', requerido: true, largo: 3000 },
    { nombre: 'fotoClave', etiqueta: 'Foto', tipo: 'imagen' },
  ];
}

const ESTADOS_PROYECTO = [
  { valor: 'borrador', texto: 'Borrador' },
  { valor: 'publicado', texto: 'Publicado' },
  { valor: 'finalizado', texto: 'Finalizado' },
  { valor: 'cancelado', texto: 'Cancelado' },
];

async function proyectos({ params, ir, recargar }) {
  const cat = await catalogos();
  if (params[0]) {
    const nuevo = params[0] === 'nuevo';
    const [p, lista] = await Promise.all([
      nuevo ? Promise.resolve(null) : get(`/v1/admin/proyectos/${encodeURIComponent(params[0])}`),
      todas('/v1/admin/asociaciones', {}, 500),
    ]);
    return el(
      'div',
      {},
      encabezado(
        nuevo ? 'Nuevo proyecto' : p.titulo,
        p
          ? filtroSelect(ESTADOS_PROYECTO, p.estado, async (v) => {
              try {
                await post(`/v1/admin/proyectos/${p.id}/estado`, { estado: v });
                aviso('Estado actualizado');
              } catch (e) {
                aviso(e.message, 'error');
              }
            }, 'Estado')
          : null,
      ),
      el(
        'div',
        { class: 'tarjeta' },
        formulario(camposProyecto(cat, lista), {
          valores: p || {},
          textoBoton: nuevo ? 'Crear proyecto' : 'Guardar',
          alCancelar: () => ir('#/proyectos'),
          enviar: async (d) => {
            if (nuevo) await post('/v1/admin/proyectos', d);
            else await put(`/v1/admin/proyectos/${p.id}`, d);
            aviso(nuevo ? 'Proyecto creado' : 'Cambios guardados');
            if (nuevo) ir('#/proyectos');
            else recargar();
          },
        }),
      ),
    );
  }
  const lista = await get('/v1/admin/proyectos');
  return el(
    'div',
    {},
    encabezado('Proyectos', enlaceBoton('#/proyectos/nuevo', 'Nuevo proyecto')),
    tabla(
      [
        { titulo: 'Proyecto', valor: (p) => el('a', { href: `#/proyectos/${p.id}`, text: p.titulo }) },
        { titulo: 'Asociación', valor: (p) => p.asociacion || 'Sin asociación' },
        { titulo: 'Ciudad', valor: (p) => p.ciudad },
        { titulo: 'Fechas', valor: (p) => `${fecha(p.fechaInicio)}${p.fechaFin ? ` a ${fecha(p.fechaFin)}` : ''}` },
        { titulo: 'Campañas', valor: (p) => p.campanas },
        { titulo: 'Estado', valor: (p) => chip(p.estado) },
      ],
      lista,
      'Todavía no hay proyectos',
    ),
  );
}

// ---------------- Campañas ----------------

async function campanas({ params, ir, recargar }) {
  const cat = await catalogos();
  if (params[0] === 'nueva') {
    const [lista, proyectosLista] = await Promise.all([todas('/v1/admin/asociaciones', {}, 500), get('/v1/admin/proyectos')]);
    return el(
      'div',
      {},
      encabezado('Nueva campaña de donación'),
      el('p', { class: 'nota', text: 'La campaña se crea como borrador. Cámbiala a publicada en el listado cuando esté lista.' }),
      el(
        'div',
        { class: 'tarjeta' },
        formulario(
          [
            { nombre: 'titulo', etiqueta: 'Título', requerido: true, largo: 150 },
            {
              nombre: 'asociacionId',
              etiqueta: 'Asociación',
              tipo: 'select',
              opciones: opcionesAsociacion(lista),
              vacio: 'Sin asociación',
              ayuda: 'Indica una asociación, un proyecto o ambos',
            },
            {
              nombre: 'proyectoId',
              etiqueta: 'Proyecto',
              tipo: 'select',
              opciones: proyectosLista.map((p) => ({ valor: p.id, texto: p.titulo })),
              vacio: 'Sin proyecto',
            },
            { nombre: 'ciudadId', etiqueta: 'Ciudad', tipo: 'select', requerido: true, opciones: opcionesCiudad(cat) },
            { nombre: 'inicio', etiqueta: 'Inicio', tipo: 'fechahora', requerido: true },
            { nombre: 'fin', etiqueta: 'Fin', tipo: 'fechahora', requerido: true },
            { nombre: 'urgente', etiqueta: 'Urgente (aparece primero)', tipo: 'casilla' },
            { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'area', requerido: true, largo: 3000 },
            { nombre: 'fotoClave', etiqueta: 'Foto', tipo: 'imagen' },
            {
              nombre: 'articulos',
              etiqueta: 'Artículos que se necesitan',
              tipo: 'lista',
              minimo: 1,
              textoAgregar: 'Agregar artículo',
              campos: [
                { nombre: 'nombre', etiqueta: 'Artículo', requerido: true, largo: 120 },
                { nombre: 'unidad', etiqueta: 'Unidad', requerido: true, largo: 30, ayuda: 'Por ejemplo piezas, kg, litros' },
                { nombre: 'cantidadMeta', etiqueta: 'Meta', tipo: 'numero', requerido: true, min: 0 },
                {
                  nombre: 'prioridad',
                  etiqueta: 'Prioridad',
                  tipo: 'select',
                  requerido: true,
                  porDefecto: 'media',
                  opciones: [
                    { valor: 'baja', texto: 'Baja' },
                    { valor: 'media', texto: 'Media' },
                    { valor: 'alta', texto: 'Alta' },
                    { valor: 'urgente', texto: 'Urgente' },
                  ],
                },
                { nombre: 'descripcion', etiqueta: 'Detalle', largo: 500, ancho: true },
              ],
            },
            {
              nombre: 'puntosEntrega',
              etiqueta: 'Puntos de entrega',
              tipo: 'lista',
              minimo: 1,
              textoAgregar: 'Agregar punto de entrega',
              campos: [
                { nombre: 'nombre', etiqueta: 'Nombre', requerido: true, largo: 150 },
                { nombre: 'ciudadId', etiqueta: 'Ciudad', tipo: 'select', requerido: true, opciones: opcionesCiudad(cat) },
                { nombre: 'direccion', etiqueta: 'Dirección', requerido: true, largo: 300, ancho: true },
                { nombre: 'horarios', etiqueta: 'Horarios', requerido: true, largo: 500 },
                { nombre: 'indicaciones', etiqueta: 'Indicaciones', largo: 500 },
                { nombre: 'latitud', etiqueta: 'Latitud', tipo: 'numero', min: -90, max: 90 },
                { nombre: 'longitud', etiqueta: 'Longitud', tipo: 'numero', min: -180, max: 180 },
              ],
            },
          ],
          {
            
            textoBoton: 'Crear campaña',
            alCancelar: () => ir('#/campanas'),
            enviar: async (d) => {
              await post('/v1/admin/campanas', d);
              aviso('Campaña creada');
              ir('#/campanas');
            },
          },
        ),
      ),
    );
  }

  const estado = { estado: '' };
  const resultados = el('div');
  const cargar = async () => {
    const lista = await get(conFiltros('/v1/admin/campanas', estado));
    vaciar(
      resultados,
      tabla(
        [
          { titulo: 'Campaña', valor: (c) => [c.titulo, c.urgente ? el('span', { class: 'chip mal', text: 'Urgente' }) : null] },
          { titulo: 'Asociación o proyecto', valor: (c) => [c.asociacion || '', c.proyecto ? el('div', { class: 'ayuda', text: c.proyecto }) : null] },
          { titulo: 'Ciudad', valor: (c) => c.ciudad },
          { titulo: 'Fechas', valor: (c) => `${fecha(c.inicio)} a ${fecha(c.fin)}` },
          { titulo: 'Avance', valor: (c) => [barraAvance(c.avance), `${c.avance}%`] },
          {
            titulo: 'Estado',
            valor: (c) =>
              filtroSelect(ESTADOS_ACTIVIDAD, c.estado, async (v) => {
                try {
                  await post(`/v1/admin/campanas/${c.id}/estado`, { estado: v });
                  aviso('Estado actualizado');
                } catch (e) {
                  aviso(e.message, 'error');
                  recargar();
                }
              }, 'Estado'),
          },
        ],
        lista,
        'No hay campañas con ese filtro',
      ),
    );
  };
  await cargar();
  return el(
    'div',
    {},
    encabezado('Campañas de donación', enlaceBoton('#/campanas/nueva', 'Nueva campaña')),
    el(
      'div',
      { class: 'barra' },
      filtroSelect(ESTADOS_ACTIVIDAD, '', (v) => {
        estado.estado = v;
        cargar();
      }, 'Todos los estados'),
      el('a', { href: '#/entregas', class: 'boton', text: 'Ver entregas de donativos' }),
    ),
    resultados,
  );
}

export const vistasContenido = { inicio, asociaciones, actividades, encuestas, proyectos, campanas };
