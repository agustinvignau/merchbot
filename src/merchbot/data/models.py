"""Modelos de datos del merchbot.

Diseño: tabla plana.
Cada fila de StockItem = un SKU único (combinación producto + modelo + color + talle).
Mapeo 1:1 con las filas del Google Sheets.

Decisión: NO normalizamos en ProductoBase + Variante porque:
- El Sheets ya es la fuente de verdad: una fila = un SKU.
- El bot busca por combinación de atributos, no por jerarquía.
- Si en el futuro hace falta normalizar (para reportes), migramos.
"""
from sqlalchemy import Column, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

from merchbot.timeutils import utc_now


Base = declarative_base()


class StockItem(Base):
    """Un SKU del inventario. Mapeo 1:1 con una fila del Sheets 'Stock'."""

    __tablename__ = "stock_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(32), unique=True, index=True, nullable=False)

    # Atributos del producto (denormalizados a propósito)
    producto = Column(String(60), nullable=False, index=True)   # "Remera", "Buzo", "Taza"
    modelo = Column(String(80), nullable=False)                  # "Cuello Redondo", "Dry-Fit"
    color = Column(String(40), nullable=False, index=True)       # "Negro", "Blanco"
    talle = Column(String(20), nullable=False)                   # "S", "M", "L", "Único"

    # Datos de stock (vienen del Sheets)
    stock_inicial = Column(Integer, nullable=False, default=0)
    ingresos = Column(Integer, nullable=False, default=0)
    pedidos = Column(Integer, nullable=False, default=0)
    stock_actual = Column(Integer, nullable=False, default=0)
    estado = Column(String(16), nullable=False, default="OK")    # "OK" o "COMPRAR"

    # Metadata
    last_synced_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Índices compuestos útiles para búsquedas frecuentes
    __table_args__ = (
        Index("ix_producto_color_talle", "producto", "color", "talle"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StockItem {self.sku} {self.producto} {self.modelo} "
            f"{self.color} {self.talle} stock={self.stock_actual}>"
        )

    @property
    def descripcion_completa(self) -> str:
        """Descripción legible: 'Remera Cuello Redondo Negro M'."""
        return f"{self.producto} {self.modelo} {self.color} {self.talle}"

    @property
    def en_rojo(self) -> bool:
        """True si hay que comprar (stock negativo o cero)."""
        return self.stock_actual <= 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sku": self.sku,
            "producto": self.producto,
            "modelo": self.modelo,
            "color": self.color,
            "talle": self.talle,
            "descripcion": self.descripcion_completa,
            "stock_inicial": self.stock_inicial,
            "ingresos": self.ingresos,
            "pedidos": self.pedidos,
            "stock_actual": self.stock_actual,
            "estado": self.estado,
            "en_rojo": self.en_rojo,
        }


class Pedido(Base):
    """Histórico de pedidos. Mapeo 1:1 con una fila del Sheets 'Pedidos'."""

    __tablename__ = "pedidos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(Date, nullable=False, index=True)
    cliente = Column(String(160), nullable=False, index=True)
    sku = Column(String(32), nullable=False, index=True)
    producto = Column(String(160), nullable=False)   # descripción denormalizada
    cantidad = Column(Integer, nullable=False)

    last_synced_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Pedido {self.fecha} {self.cliente} {self.sku} x{self.cantidad}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fecha": self.fecha.isoformat() if self.fecha else None,
            "cliente": self.cliente,
            "sku": self.sku,
            "producto": self.producto,
            "cantidad": self.cantidad,
        }


class Mensaje(Base):
    """Un turno de conversación (memoria persistente del asistente).

    `user_id` es texto para servir a las dos interfaces: el ID numérico de
    Telegram o el ID de sesión de la web.
    """

    __tablename__ = "mensajes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role = Column(String(8), nullable=False)        # "user" o "model"
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Mensaje {self.user_id} {self.role} {self.text[:30]!r}>"
