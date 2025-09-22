"""
Базовые классы для моделей SQLAlchemy
"""
from typing import Any, Dict, List, Optional, Type, TypeVar
from datetime import datetime, timezone
import uuid

from sqlalchemy import String, DateTime, Boolean, Integer, BigInteger, Text
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func

from app.core.database import Base

ModelType = TypeVar("ModelType", bound="BaseModel")


class TimestampMixin:
    """Mixin для добавления временных меток"""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Дата и время создания записи"
    )
    
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Дата и время последнего обновления записи"
    )


class SoftDeleteMixin:
    """Mixin для мягкого удаления записей"""
    
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        comment="Флаг удаления записи (мягкое удаление)"
    )
    
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время удаления записи"
    )
    
    def soft_delete(self) -> None:
        """Мягкое удаление записи"""
        self.is_deleted = True
        self.deleted_at = datetime.now(timezone.utc)
    
    def restore(self) -> None:
        """Восстановление удаленной записи"""
        self.is_deleted = False
        self.deleted_at = None


class BaseModel(Base, TimestampMixin):
    """Базовая модель с общими полями и методами"""
    
    __abstract__ = True
    
    def to_dict(self, exclude: Optional[List[str]] = None) -> Dict[str, Any]:
        """Преобразование модели в словарь"""
        exclude = exclude or []
        result = {}
        
        for column in self.__table__.columns:
            if column.name not in exclude:
                value = getattr(self, column.name)
                
                # Преобразование специальных типов
                if isinstance(value, datetime):
                    result[column.name] = value.isoformat()
                elif isinstance(value, uuid.UUID):
                    result[column.name] = str(value)
                else:
                    result[column.name] = value
        
        return result
    
    def update_from_dict(self, data: Dict[str, Any]) -> None:
        """Обновление модели из словаря"""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    @classmethod
    async def get_by_id(
        cls: Type[ModelType], 
        session: AsyncSession, 
        id: uuid.UUID
    ) -> Optional[ModelType]:
        """Получение записи по ID"""
        result = await session.execute(
            select(cls).where(cls.id == id)
        )
        return result.scalar_one_or_none()
    
    @classmethod
    async def get_all(
        cls: Type[ModelType],
        session: AsyncSession,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[ModelType]:
        """Получение всех записей"""
        query = select(cls)
        
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def create(
        cls: Type[ModelType],
        session: AsyncSession,
        **kwargs
    ) -> ModelType:
        """Создание новой записи"""
        instance = cls(**kwargs)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        return instance
    
    async def update(
        self,
        session: AsyncSession,
        **kwargs
    ) -> None:
        """Обновление записи"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        
        await session.flush()
    
    async def delete(self, session: AsyncSession) -> None:
        """Удаление записи"""
        await session.delete(self)
        await session.flush()
    
    @classmethod
    async def count(cls: Type[ModelType], session: AsyncSession) -> int:
        """Подсчет количества записей"""
        result = await session.execute(
            select(func.count(cls.id))
        )
        return result.scalar()
    
    @classmethod
    async def exists(
        cls: Type[ModelType],
        session: AsyncSession,
        **filters
    ) -> bool:
        """Проверка существования записи"""
        query = select(cls.id)
        
        for key, value in filters.items():
            if hasattr(cls, key):
                query = query.where(getattr(cls, key) == value)
        
        result = await session.execute(query)
        return result.first() is not None


class CacheableMixin:
    """Mixin для кешируемых моделей"""
    
    @property
    def cache_key(self) -> str:
        """Ключ для кеширования"""
        return f"{self.__class__.__name__.lower()}:{self.id}"
    
    @classmethod
    def cache_key_pattern(cls, pattern: str = "*") -> str:
        """Паттерн ключей для кеширования"""
        return f"{cls.__name__.lower()}:{pattern}"


class StatsMixin:
    """Mixin для моделей со статистикой"""
    
    views_count: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
        comment="Количество просмотров"
    )
    
    downloads_count: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
        comment="Количество скачиваний"
    )
    
    likes_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="Количество лайков"
    )
    
    async def increment_views(self, session: AsyncSession) -> None:
        """Увеличение счетчика просмотров"""
        self.views_count += 1
        await session.flush()
    
    async def increment_downloads(self, session: AsyncSession) -> None:
        """Увеличение счетчика скачиваний"""
        self.downloads_count += 1
        await session.flush()
    
    async def increment_likes(self, session: AsyncSession) -> None:
        """Увеличение счетчика лайков"""
        self.likes_count += 1
        await session.flush()
    
    async def decrement_likes(self, session: AsyncSession) -> None:
        """Уменьшение счетчика лайков"""
        if self.likes_count > 0:
            self.likes_count -= 1
            await session.flush()


class MetadataMixin:
    """Mixin для хранения метаданных в JSONB"""
    
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Дополнительные метаданные в формате JSON"
    )
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Получение значения из метаданных"""
        if not self.metadata:
            return default
        return self.metadata.get(key, default)
    
    def set_metadata(self, key: str, value: Any) -> None:
        """Установка значения в метаданных"""
        if not self.metadata:
            self.metadata = {}
        self.metadata[key] = value
    
    def update_metadata(self, data: Dict[str, Any]) -> None:
        """Обновление метаданных"""
        if not self.metadata:
            self.metadata = {}
        self.metadata.update(data)
    
    def remove_metadata(self, key: str) -> None:
        """Удаление ключа из метаданных"""
        if self.metadata and key in self.metadata:
            del self.metadata[key]


class SearchableMixin:
    """Mixin для поисковых индексов"""
    
    search_vector: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Поисковый вектор для полнотекстового поиска"
    )
    
    def update_search_vector(self, *fields: str) -> None:
        """Обновление поискового вектора"""
        search_text = " ".join(
            str(getattr(self, field, "")) for field in fields
        )
        self.search_vector = search_text.lower()


class VersionedMixin:
    """Mixin для версионирования записей"""
    
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        comment="Версия записи"
    )
    
    def increment_version(self) -> None:
        """Увеличение версии записи"""
        self.version += 1


class AuditMixin:
    """Mixin для аудита изменений"""
    
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="ID пользователя, создавшего запись"
    )
    
    updated_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="ID пользователя, обновившего запись"
    )
    
    def set_created_by(self, user_id: int) -> None:
        """Установка создателя записи"""
        self.created_by = user_id
    
    def set_updated_by(self, user_id: int) -> None:
        """Установка обновившего запись"""
        self.updated_by = user_id