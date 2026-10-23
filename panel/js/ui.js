// Piezas de interfaz del panel. Todo el texto se coloca con textContent o nodos de texto,
// nunca como HTML, así un nombre o una descripción con etiquetas se ve tal cual y no se
// ejecuta (defensa contra XSS además de la política CSP).

import { ErrorApi, subirImagen } from './api.js';

/** Crea un elemento. Las propiedades on* son manejadores, class y text son atajos. */
export function el(etiqueta, props = {}, ...hijos) {
  const n = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = String(v);
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else if (k === 'value') n.value = v;
    else if (k === 'checked') n.checked = !!v;
    else n.setAttribute(k, v === true ? '' : String(v));
  }
  agregar(n, hijos);
  return n;
}

function agregar(n, hijos) {
  for (const h of hijos) {
    if (h === null || h === undefined || h === false) continue;
    if (Array.isArray(h)) agregar(n, h);
    else if (h instanceof Node) n.appendChild(h);
    else n.appendChild(document.createTextNode(String(h)));
  }
}

export function vaciar(n, ...hijos) {
  n.replaceChildren();
  agregar(n, hijos);
  return n;
}

// ---------------- Formatos ----------------

const fmtFechaHora = new Intl.DateTimeFormat('es-MX', { dateStyle: 'medium', timeStyle: 'short' });
const fmtFecha = new Intl.DateTimeFormat('es-MX', { dateStyle: 'medium' });

export function fechaHora(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : fmtFechaHora.format(d);
}
export function fecha(iso) {
  if (!iso) return '';
  const d = new Date(String(iso).length === 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime()) ? String(iso) : fmtFecha.format(d);
}

/** ISO a valor de un input datetime-local (hora del navegador). */
export function aLocal(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

const NOMBRES_ESTADO = {
  borrador: ['Borrador', 'neutro'],
  publicada: ['Publicada', 'bien'],
  publicado: ['Publicado', 'bien'],
  finalizada: ['Finalizada', 'neutro'],
  finalizado: ['Finalizado', 'neutro'],
  cancelada: ['Cancelada', 'mal'],
  cancelado: ['Cancelado', 'mal'],
  activo: ['Activa', 'bien'],
  suspendido: ['Suspendida', 'mal'],
  pendiente_eliminacion: ['Por eliminar', 'espera'],
  pendiente: ['Pendiente', 'espera'],
  en_revision: ['En revisión', 'espera'],
  en_proceso: ['En proceso', 'espera'],
  necesita_cambios: ['Necesita cambios', 'espera'],
  aprobada: ['Aprobada', 'bien'],
  aprobado: ['Aprobado', 'bien'],
  rechazada: ['Rechazada', 'mal'],
  rechazado: ['Rechazado', 'mal'],
  completada: ['Completada', 'bien'],
  resuelto: ['Resuelto', 'bien'],
  registrada: ['Registrada', 'espera'],
  recibida: ['Recibida', 'bien'],
  confirmada: ['Confirmada', 'bien'],
  asistio: ['Asistió', 'bien'],
  no_asistio: ['No asistió', 'mal'],
};

export function chip(estado) {
  const [texto, clase] = NOMBRES_ESTADO[estado] || [estado, 'neutro'];
  return el('span', { class: `chip ${clase}`, text: texto });
}
export const siNo = (v, si = 'Sí', no = 'No') => el('span', { class: `chip ${v ? 'bien' : 'neutro'}`, text: v ? si : no });

// ---------------- Avisos y diálogos ----------------

export function aviso(texto, tipo = 'ok') {
  const caja = document.getElementById('avisos');
  const n = el('div', { class: `aviso ${tipo === 'error' ? 'error' : ''}`, text: texto });
  caja.appendChild(n);
  setTimeout(() => n.remove(), tipo === 'error' ? 7000 : 3500);
}

export function avisoError(e) {
  aviso(e instanceof ErrorApi ? e.message : 'Ocurrió un error inesperado', 'error');
  if (!(e instanceof ErrorApi)) console.error(e);
}

/** Abre un diálogo modal. Devuelve una función para cerrarlo. */
export function dialogo(titulo, contenido, { alCerrar } = {}) {
  const d = el('dialog', {}, el('h2', { text: titulo }), contenido);
  const cerrar = () => {
    d.close();
    d.remove();
    if (alCerrar) alCerrar();
  };
  d.addEventListener('cancel', (ev) => {
    ev.preventDefault();
    cerrar();
  });
  document.body.appendChild(d);
  d.showModal();
  return cerrar;
}

export function confirmar(mensaje, { textoSi = 'Confirmar', peligro = false } = {}) {
  return new Promise((resolver) => {
    let cerrar = null;
    const responder = (v) => {
      cerrar();
      resolver(v);
    };
    const pie = el(
      'div',
      { class: 'pie-dialogo' },
      el('button', { type: 'button', onclick: () => responder(false), text: 'Cancelar' }),
      el('button', { type: 'button', class: peligro ? 'peligro' : 'primario', onclick: () => responder(true), text: textoSi }),
    );
    cerrar = dialogo('Confirmar', el('div', {}, el('p', { text: mensaje }), pie), {});
  });
}

// ---------------- Tablas ----------------

/**
 * columnas es una lista de { titulo, valor(fila) } donde valor devuelve texto o un nodo.
 */
export function tabla(columnas, filas, vacio = 'No hay registros') {
  if (!filas.length) return el('div', { class: 'tabla-envoltura' }, el('div', { class: 'vacio', text: vacio }));
  return el(
    'div',
    { class: 'tabla-envoltura' },
    el(
      'table',
      {},
      el('thead', {}, el('tr', {}, columnas.map((c) => el('th', { text: c.titulo })))),
      el(
        'tbody',
        {},
        filas.map((f) => el('tr', {}, columnas.map((c) => el('td', { class: c.clase || null }, c.valor(f))))),
      ),
    ),
  );
}

export function barraAvance(porcentaje) {
  const s = el('span');
  s.style.width = `${Math.max(0, Math.min(100, porcentaje))}%`;
  return el('div', { class: 'barra-avance', title: `${porcentaje}%` }, s);
}

export function ficha(pares) {
  return el(
    'dl',
    { class: 'ficha' },
    pares.filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => [el('dt', { text: k }), el('dd', {}, v)]),
  );
}

// ---------------- Formularios ----------------

/**
 * Construye un formulario a partir de una lista de campos.
 *
 * Tipos de campo
 *  texto, area, correo, tel, url, numero, entero, select, casilla, fechahora, fecha, imagen,
 *  lineas (una opción por renglón, se envía como lista), lista (elementos repetibles).
 *
 * Los valores vacíos de campos opcionales no se envían, así la API usa su valor por omisión.
 */
export function formulario(campos, { valores = {}, textoBoton = 'Guardar', enviar, alCancelar, extra } = {}) {
  const form = el('form', { class: 'formulario', novalidate: true });
  const lectores = [];
  for (const c of campos) {
    const r = construirCampo(c, valores[c.nombre]);
    form.appendChild(r.nodo);
    lectores.push([c, r]);
  }
  const caja = el('div', { class: 'error-form', hidden: true });
  const boton = el('button', { type: 'submit', class: 'primario', text: textoBoton });
  form.appendChild(caja);
  form.appendChild(
    el(
      'div',
      { class: 'acciones-form' },
      boton,
      alCancelar ? el('button', { type: 'button', onclick: alCancelar, text: 'Cancelar' }) : null,
      extra || null,
    ),
  );

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    caja.hidden = true;
    form.querySelectorAll('.con-error').forEach((n) => n.classList.remove('con-error'));
    form.querySelectorAll('.error-campo').forEach((n) => n.remove());
    const datos = {};
    const faltan = [];
    for (const [c, r] of lectores) {
      const v = r.leer();
      if (c.requerido && (v === null || v === '' || (Array.isArray(v) && !v.length))) faltan.push(c);
      if (r.faltantes) faltan.push(...r.faltantes());
      if (v !== null && v !== undefined) datos[c.nombre] = v;
    }
    if (faltan.length) {
      mostrarErrores(form, caja, 'Completa los campos obligatorios', faltan.map((c) => ({ campo: c.nombre, mensaje: `${c.etiqueta} es obligatorio` })));
      return;
    }
    boton.disabled = true;
    try {
      await enviar(datos);
    } catch (e) {
      if (e instanceof ErrorApi) mostrarErrores(form, caja, e.message, Array.isArray(e.detalles) ? e.detalles : []);
      else avisoError(e);
    } finally {
      boton.disabled = false;
    }
  });
  return form;
}

function mostrarErrores(form, caja, mensaje, detalles) {
  vaciar(caja, el('strong', { text: mensaje }));
  const lista = el('ul');
  for (const d of detalles) {
    if (!d || typeof d !== 'object') continue;
    const nombre = String(d.campo || '').split('.')[0];
    const campo = nombre ? form.querySelector(`[data-campo="${CSS.escape(nombre)}"]`) : null;
    if (campo) {
      campo.classList.add('con-error');
      campo.appendChild(el('span', { class: 'error-campo', text: d.mensaje }));
    }
    lista.appendChild(el('li', { text: d.campo ? `${d.campo}, ${d.mensaje}` : d.mensaje }));
  }
  if (lista.children.length) caja.appendChild(lista);
  caja.hidden = false;
  caja.scrollIntoView({ block: 'nearest' });
}

let contador = 0;

function construirCampo(c, valor) {
  const id = `c${++contador}`;
  const envoltura = el('div', { class: `campo ${c.ancho || c.tipo === 'area' ? 'ancho' : ''}`, 'data-campo': c.nombre });
  const etiqueta = el('label', { for: id, text: c.etiqueta + (c.requerido ? ' *' : '') });
  const ayuda = c.ayuda ? el('span', { class: 'ayuda', text: c.ayuda }) : null;
  const vacioANull = (t) => (t === '' ? null : t);

  switch (c.tipo) {
    case 'area': {
      const n = el('textarea', { id, maxlength: c.largo || null, rows: c.filas || 4 });
      n.value = valor ?? '';
      envoltura.append(etiqueta, n);
      if (ayuda) envoltura.append(ayuda);
      return { nodo: envoltura, leer: () => vacioANull(n.value.trim()) };
    }
    case 'select': {
      // Un campo obligatorio con valor (o con valor por omisión) no ofrece la opción vacía.
      // Sin valor, la opción vacía obliga a elegir a conciencia (por ejemplo la asociación).
      const inicial = valor ?? c.porDefecto ?? '';
      const n = el(
        'select',
        { id },
        c.requerido && inicial !== '' ? null : el('option', { value: '', text: c.requerido ? 'Elige una opción' : c.vacio || 'Sin seleccionar' }),
        (c.opciones || []).map((o) => el('option', { value: o.valor, text: o.texto })),
      );
      n.value = inicial;
      envoltura.append(etiqueta, n);
      if (ayuda) envoltura.append(ayuda);
      return { nodo: envoltura, leer: () => vacioANull(n.value) };
    }
    case 'casilla': {
      envoltura.classList.add('casilla');
      const n = el('input', { id, type: 'checkbox', checked: valor ?? c.porDefecto ?? false });
      envoltura.append(n, etiqueta);
      if (ayuda) envoltura.append(ayuda);
      return { nodo: envoltura, leer: () => n.checked };
    }
    case 'numero':
    case 'entero': {
      const n = el('input', { id, type: 'number', min: c.min ?? null, max: c.max ?? null, step: c.tipo === 'entero' ? 1 : c.paso || 'any' });
      n.value = valor ?? '';
      envoltura.append(etiqueta, n);
      if (ayuda) envoltura.append(ayuda);
      return { nodo: envoltura, leer: () => (n.value === '' ? null : Number(n.value)) };
    }
    case 'fechahora': {
      const n = el('input', { id, type: 'datetime-local' });
      n.value = aLocal(valor);
      envoltura.append(etiqueta, n);
      envoltura.append(el('span', { class: 'ayuda', text: c.ayuda || 'Hora local de esta computadora' }));
      return { nodo: envoltura, leer: () => (n.value ? new Date(n.value).toISOString() : null) };
    }
    case 'fecha': {
      const n = el('input', { id, type: 'date' });
      n.value = valor ?? '';
      envoltura.append(etiqueta, n);
      if (ayuda) envoltura.append(ayuda);
      return { nodo: envoltura, leer: () => vacioANull(n.value) };
    }
    case 'imagen':
      return campoImagen(c, id, envoltura, etiqueta, ayuda, valor);
    case 'lineas': {
      const n = el('textarea', { id, rows: c.filas || 3 });
      n.value = Array.isArray(valor) ? valor.join('\n') : '';
      envoltura.append(etiqueta, n, el('span', { class: 'ayuda', text: c.ayuda || 'Una por renglón' }));
      return {
        nodo: envoltura,
        leer: () =>
          n.value
            .split('\n')
            .map((t) => t.trim())
            .filter(Boolean),
      };
    }
    case 'lista':
      return campoLista(c, valor);
    default: {
      const tipos = { correo: 'email', tel: 'tel', url: 'url', contrasena: 'password' };
      const n = el('input', {
        id,
        type: tipos[c.tipo] || 'text',
        maxlength: c.largo || null,
        autocomplete: c.autocompletar || 'off',
        inputmode: c.modo || null,
      });
      n.value = valor ?? '';
      envoltura.append(etiqueta, n);
      if (ayuda) envoltura.append(ayuda);
      return { nodo: envoltura, leer: () => vacioANull(n.value.trim()) };
    }
  }
}

/** Sube la imagen a /v1/archivos (la API la limpia y reconstruye) y guarda su clave. */
function campoImagen(c, id, envoltura, etiqueta, ayuda, valor) {
  let clave = valor || null;
  const vista = el('img', { alt: '' });
  const refrescar = () => {
    if (clave) vista.src = `/v1/archivos/${clave}`;
    else vista.removeAttribute('src');
    quitar.hidden = !clave;
  };
  const entrada = el('input', { id, type: 'file', accept: 'image/jpeg,image/png' });
  const quitar = el('button', {
    type: 'button',
    class: 'chico',
    text: 'Quitar',
    onclick: () => {
      clave = null;
      refrescar();
    },
  });
  entrada.addEventListener('change', async () => {
    const f = entrada.files && entrada.files[0];
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) {
      aviso('La imagen pesa más de 5 MB', 'error');
      return;
    }
    try {
      const r = await subirImagen(f);
      clave = r.clave;
      refrescar();
      aviso('Imagen subida');
    } catch (e) {
      avisoError(e);
    } finally {
      entrada.value = '';
    }
  });
  envoltura.append(etiqueta, el('div', { class: 'foto' }, vista, el('div', {}, entrada, quitar)));
  envoltura.append(ayuda || el('span', { class: 'ayuda', text: 'JPEG o PNG de máximo 5 MB. Se le quitan los metadatos.' }));
  refrescar();
  return { nodo: envoltura, leer: () => clave };
}

/** Lista de elementos repetibles (artículos de una campaña, preguntas de una encuesta). */
function campoLista(c, valor) {
  const caja = el('div', { class: 'repetible', 'data-campo': c.nombre }, el('div', { class: 'titulo', text: c.etiqueta }));
  const elementos = [];
  const contenedor = el('div');
  const agregarElemento = (v = {}) => {
    const lectores = [];
    const nodo = el('div', { class: 'elemento' });
    for (const sub of c.campos) {
      const r = construirCampo(sub, v[sub.nombre]);
      nodo.appendChild(r.nodo);
      lectores.push([sub, r]);
    }
    const item = { nodo, lectores };
    nodo.appendChild(
      el('button', {
        type: 'button',
        class: 'chico peligro quitar',
        text: 'Quitar',
        onclick: () => {
          if (elementos.length <= (c.minimo || 0)) {
            aviso(`Debe haber al menos ${c.minimo}`, 'error');
            return;
          }
          elementos.splice(elementos.indexOf(item), 1);
          nodo.remove();
        },
      }),
    );
    elementos.push(item);
    contenedor.appendChild(nodo);
  };
  const iniciales = Array.isArray(valor) && valor.length ? valor : Array.from({ length: c.minimo || 1 }, () => ({}));
  iniciales.forEach((v) => agregarElemento(v));
  caja.append(contenedor, el('button', { type: 'button', class: 'chico', text: c.textoAgregar || 'Agregar', onclick: () => agregarElemento() }));
  if (c.ayuda) caja.append(el('p', { class: 'ayuda', text: c.ayuda }));
  return {
    nodo: caja,
    // Campos obligatorios vacíos dentro de cada elemento, con su número para ubicarlos
    faltantes: () =>
      elementos.flatMap(({ lectores }, i) =>
        lectores
          .filter(([sub, r]) => sub.requerido && sub.tipo !== 'casilla' && (r.leer() === null || r.leer() === ''))
          .map(([sub]) => ({ nombre: c.nombre, etiqueta: `${sub.etiqueta} (${i + 1})` })),
      ),
    leer: () =>
      elementos.map(({ lectores }) => {
        const o = {};
        for (const [sub, r] of lectores) {
          const v = r.leer();
          if (v !== null && v !== undefined) o[sub.nombre] = v;
        }
        return o;
      }),
  };
}

/** Selector de opciones para filtros de listados. */
export function filtroSelect(opciones, valor, alCambiar, vacio = 'Todos') {
  const s = el('select', {}, el('option', { value: '', text: vacio }), opciones.map((o) => el('option', { value: o.valor, text: o.texto })));
  s.value = valor || '';
  s.addEventListener('change', () => alCambiar(s.value));
  return s;
}

export function buscador(valor, alBuscar, placeholder = 'Buscar') {
  const i = el('input', { type: 'search', placeholder, value: valor || '' });
  let t = null;
  i.addEventListener('input', () => {
    clearTimeout(t);
    t = setTimeout(() => alBuscar(i.value.trim()), 350);
  });
  return i;
}

/** Botón que ejecuta una acción, se desactiva mientras corre y avisa el error si falla. */
export function botonAccion(texto, accion, { clase = 'chico', confirmacion, peligro = false } = {}) {
  const b = el('button', { type: 'button', class: `${clase} ${peligro ? 'peligro' : ''}`, text: texto });
  b.addEventListener('click', async () => {
    if (confirmacion && !(await confirmar(confirmacion, { peligro, textoSi: texto }))) return;
    b.disabled = true;
    try {
      await accion();
    } catch (e) {
      avisoError(e);
    } finally {
      b.disabled = false;
    }
  });
  return b;
}
