// Cliente de la API para el panel. Los tokens viven en cookies HttpOnly, este código nunca
// los ve. Cada petición lleva el encabezado X-FQS-Panel, que la API exige para todo lo que
// cambia datos con cookie (defensa contra CSRF).

const ENCABEZADO_PANEL = { 'X-FQS-Panel': '1' };

export class ErrorApi extends Error {
  constructor(status, codigo, mensaje, detalles) {
    super(mensaje);
    this.status = status;
    this.codigo = codigo;
    this.detalles = detalles;
  }
}

let alExpirar = () => {};
/** Qué hacer cuando la sesión venció y no se pudo renovar (volver a la pantalla de acceso). */
export function cuandoExpire(f) {
  alExpirar = f;
}

let renovacionEnCurso = null;
function renovar() {
  // Si varias peticiones reciben 401 al mismo tiempo, se renueva una sola vez
  if (!renovacionEnCurso) {
    renovacionEnCurso = fetch('/v1/panel/sesion/renovar', {
      method: 'POST',
      headers: ENCABEZADO_PANEL,
      credentials: 'same-origin',
    })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        setTimeout(() => {
          renovacionEnCurso = null;
        }, 0);
      });
  }
  return renovacionEnCurso;
}

const esRutaDeSesion = (metodo, ruta) => metodo === 'POST' && ruta.startsWith('/v1/panel/sesion');

export async function api(metodo, ruta, cuerpo, opciones = {}) {
  const init = { method: metodo, headers: { ...ENCABEZADO_PANEL }, credentials: 'same-origin', cache: 'no-store' };
  if (opciones.archivo) {
    init.headers['Content-Type'] = opciones.archivo.type;
    init.body = opciones.archivo;
  } else if (cuerpo !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(cuerpo);
  }
  let r;
  try {
    r = await fetch(ruta, init);
  } catch {
    throw new ErrorApi(0, 'red', 'No hay conexión con el servidor');
  }
  if (r.status === 401 && !opciones.sinRenovar && !esRutaDeSesion(metodo, ruta)) {
    if (await renovar()) return api(metodo, ruta, cuerpo, { ...opciones, sinRenovar: true });
    alExpirar();
  }
  if (r.status === 204) return null;
  const json = await r.json().catch(() => null);
  if (!r.ok) {
    const e = json && json.error;
    throw new ErrorApi(r.status, e ? e.codigo : 'error', e ? e.mensaje : `Error ${r.status}`, e ? e.detalles : undefined);
  }
  return json;
}

export const get = (ruta) => api('GET', ruta);
export const post = (ruta, cuerpo) => api('POST', ruta, cuerpo ?? {});
export const put = (ruta, cuerpo) => api('PUT', ruta, cuerpo);
export const subirImagen = (archivo) => api('POST', '/v1/archivos', undefined, { archivo });

/** Arma una ruta con parámetros de búsqueda, omitiendo los vacíos. */
export function conFiltros(ruta, filtros) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(filtros)) if (v !== null && v !== undefined && v !== '') q.set(k, String(v));
  const s = q.toString();
  return s ? `${ruta}?${s}` : ruta;
}

/** Recorre un listado paginado (50 por página) hasta el final o hasta el tope indicado. */
export async function todas(ruta, filtros = {}, tope = 1000) {
  const r = [];
  for (let desplazamiento = 0; desplazamiento < tope; desplazamiento += 50) {
    const pagina = await get(conFiltros(ruta, { ...filtros, limite: 50, desplazamiento }));
    r.push(...pagina);
    if (pagina.length < 50) break;
  }
  return r;
}

let catalogo = null;
/** Ciudades y categorías, se piden una vez por sesión del panel. */
export async function catalogos(forzar = false) {
  if (!catalogo || forzar) catalogo = await get('/v1/catalogos');
  return catalogo;
}
export const borrar = (ruta) => api('DELETE', ruta);
