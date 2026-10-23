// Arranque del panel, acceso con contraseña y segundo factor, menú y navegación por hash.

import { cuandoExpire, ErrorApi, get, post } from './api.js';
import { el, formulario, vaciar, avisoError } from './ui.js';
import { vistasContenido } from './vistas/contenido.js';
import { vistasComunidad } from './vistas/comunidad.js';
import { vistasAjustes, vistaSeguridad } from './vistas/ajustes.js';

const raiz = document.getElementById('app');
let sesion = null;

const MENU = [
  ['General', [['#/inicio', 'Inicio']]],
  [
    'Contenido',
    [
      ['#/asociaciones', 'Asociaciones'],
      ['#/actividades', 'Actividades'],
      ['#/proyectos', 'Proyectos'],
      ['#/campanas', 'Campañas'],
    ],
  ],
  [
    'Comunidad',
    [
      ['#/propuestas', 'Propuestas'],
      ['#/testimonios', 'Testimonios'],
      ['#/reportes', 'Reportes'],
      ['#/entregas', 'Entregas de donativos'],
      ['#/calidad', 'Calidad de asociaciones'],
    ],
  ],
  [
    'Cuentas',
    [
      ['#/usuarios', 'Personas'],
      ['#/solicitudes', 'Solicitudes de eliminación'],
    ],
  ],
  [
    'Ajustes',
    [
      ['#/catalogos', 'Ciudades y categorías'],
      ['#/reconocimientos', 'Niveles e insignias'],
      ['#/privacidad', 'Aviso de privacidad'],
      ['#/seguridad', 'Seguridad'],
    ],
  ],
];

const VISTAS = { ...vistasContenido, ...vistasComunidad, ...vistasAjustes };

// ---------------- Acceso ----------------

function pantallaAcceso(mensaje) {
  sesion = null;
  const tarjeta = el('div', { class: 'tarjeta' });
  const caja = el('main', { class: 'acceso' }, tarjeta);
  raiz.className = '';
  vaciar(raiz, caja);

  const pasoContrasena = () => {
    vaciar(
      tarjeta,
      el('h1', { text: 'Familias que Suman' }),
      el('p', { text: 'Panel de administración. Entra con tu cuenta de administración.' }),
      mensaje ? el('p', { class: 'nota', text: mensaje }) : null,
      formulario(
        [
          { nombre: 'identificador', etiqueta: 'Correo o teléfono', requerido: true, autocompletar: 'username' },
          { nombre: 'password', etiqueta: 'Contraseña', tipo: 'contrasena', requerido: true, autocompletar: 'current-password' },
        ],
        {
          textoBoton: 'Entrar',
          enviar: async (d) => {
            const r = await post('/v1/panel/sesion', d);
            if (r.requiere2fa) pasoCodigo(r.desafio);
            else entrar(r);
          },
        },
      ),
    );
    tarjeta.querySelector('input')?.focus();
  };

  const pasoCodigo = (desafio) => {
    vaciar(
      tarjeta,
      el('h1', { text: 'Código de verificación' }),
      el('p', {
        text: 'Escribe el código de 6 dígitos de tu app de autenticación. Si no tienes el teléfono, usa uno de tus códigos de respaldo.',
      }),
      formulario([{ nombre: 'codigo', etiqueta: 'Código', requerido: true, modo: 'numeric', autocompletar: 'one-time-code' }], {
        textoBoton: 'Verificar',
        enviar: async (d) => {
          try {
            entrar(await post('/v1/panel/sesion/2fa', { desafio, codigo: d.codigo.replace(/\s/g, '') }));
          } catch (e) {
            if (e instanceof ErrorApi && e.codigo === 'desafio_invalido') {
              mensaje = e.message;
              pasoContrasena();
              return;
            }
            throw e;
          }
        },
        alCancelar: pasoContrasena,
      }),
    );
    tarjeta.querySelector('input')?.focus();
  };

  pasoContrasena();
}

function entrar(estado) {
  sesion = estado;
  if (!location.hash || location.hash === '#/') location.hash = '#/inicio';
  dibujar();
}

async function salir() {
  try {
    await post('/v1/panel/sesion/salir');
  } catch {
    // Aunque falle la llamada, las cookies se borran al vencer
  }
  location.hash = '';
  pantallaAcceso('Cerraste sesión.');
}

// ---------------- Estructura ----------------

/** Partes de la ruta del hash sin los filtros (#/actividades?asociacion=x da ['actividades']). */
const rutaHash = () => location.hash.slice(2).split('?')[0].split('/').filter(Boolean).map(decodificar);
const decodificar = (p) => {
  try {
    return decodeURIComponent(p);
  } catch {
    return p;
  }
};

function marco(contenido) {
  const actual = `#/${rutaHash()[0] || 'inicio'}`;
  const lateral = el(
    'aside',
    { class: 'lateral' },
    el('div', { class: 'marca' }, el('img', { src: '/panel/icono.svg', alt: '' }), 'Familias que Suman'),
    el(
      'nav',
      { 'aria-label': 'Secciones' },
      MENU.map(([grupo, enlaces]) => [
        el('div', { class: 'grupo', text: grupo }),
        enlaces.map(([href, texto]) => el('a', { href, text: texto, class: href === actual ? 'activo' : null })),
      ]),
    ),
    el(
      'div',
      { class: 'pie' },
      el('p', { text: sesion.usuario.nombre }),
      el('button', { type: 'button', class: 'chico', text: 'Cerrar sesión', onclick: salir }),
    ),
  );
  const menuMovil = el('button', { type: 'button', class: 'menu-movil', text: 'Menú', onclick: () => lateral.classList.toggle('abierto') });
  return el('div', { class: 'marco' }, lateral, el('div', {}, menuMovil, el('main', { class: 'contenido' }, contenido)));
}

/** Con el segundo factor obligatorio y una sesión sin código, solo se puede ir a activarlo. */
const soloSeguridad = () => sesion.segundoFactor.obligatorio && !sesion.sesionConSegundoFactor;

async function dibujar() {
  if (!sesion) return;
  const partes = rutaHash();
  let nombre = partes[0] || 'inicio';
  if (soloSeguridad() && nombre !== 'seguridad') {
    location.hash = '#/seguridad';
    return;
  }
  const contenido = el('div', { class: 'cargando', text: 'Cargando' });
  raiz.className = '';
  vaciar(raiz, marco(contenido));
  try {
    const vista = nombre === 'seguridad' ? vistaSeguridad : VISTAS[nombre];
    if (!vista) {
      vaciar(contenido, el('h1', { text: 'No encontrado' }), el('p', { text: 'Esta sección no existe.' }));
      contenido.className = '';
      return;
    }
    const nodo = await vista({
      params: partes.slice(1),
      sesion,
      recargar: dibujar,
      ir: (hash) => {
        if (location.hash === hash) dibujar();
        else location.hash = hash;
      },
      actualizarSesion: async () => {
        sesion = await get('/v1/panel/sesion');
      },
    });
    contenido.className = '';
    vaciar(contenido, nodo);
  } catch (e) {
    contenido.className = '';
    if (e instanceof ErrorApi && e.status === 401) return;
    if (e instanceof ErrorApi && e.codigo === 'requiere_2fa') {
      location.hash = '#/seguridad';
      return;
    }
    vaciar(contenido, el('h1', { text: 'No se pudo cargar' }), el('p', { class: 'nota mala', text: e.message || 'Error inesperado' }));
    avisoError(e);
  }
}

window.addEventListener('hashchange', dibujar);
cuandoExpire(() => pantallaAcceso('Tu sesión terminó. Vuelve a entrar.'));

(async () => {
  try {
    entrar(await get('/v1/panel/sesion'));
  } catch {
    pantallaAcceso();
  }
})();
