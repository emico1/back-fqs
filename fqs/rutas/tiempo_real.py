"""
GET /v1/cupos/stream
Flujo Server-Sent Events con los cambios de cupo de las actividades publicadas. Cada evento se
llama cupos y su dato es {"actividadId","cupoTotal","cuposOcupados","cuposDisponibles"}.
Requiere sesión. El aviso no contiene datos personales, solo números de lugares.
"""

from fastapi.responses import StreamingResponse

from ..http.dependencias import Svc, Usuario
from .comun import nuevo_router

router = nuevo_router("tiempo real")


@router.get("/v1/cupos/stream", summary="Cupos en tiempo real (Server-Sent Events)")
async def cupos(s: Svc, u: Usuario):
    suscriptor = s.cupos.suscribir(u.id)
    return StreamingResponse(
        s.cupos.flujo(suscriptor),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
