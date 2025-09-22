"""
Инициализация музыкальных сервисов
"""

from app.services.music.base import (
    BaseMusicService,
    SearchResult,
    DownloadResult,
    RateLimiter,
    ServiceError,
    RateLimitError,
    TrackNotFoundError,
    DownloadError,
    AuthenticationError
)

from app.services.music.vk_audio import VKAudioService
from app.services.music.youtube import YouTubeMusicService
from app.services.music.spotify import SpotifyService
from app.services.music.aggregator import (
    MusicAggregator,
    SearchStrategy,
    ServiceConfig
)

__all__ = [
    # Базовые классы
    "BaseMusicService",
    "SearchResult", 
    "DownloadResult",
    "RateLimiter",
    
    # Исключения
    "ServiceError",
    "RateLimitError",
    "TrackNotFoundError", 
    "DownloadError",
    "AuthenticationError",
    
    # Сервисы
    "VKAudioService",
    "YouTubeMusicService",
    "SpotifyService",
    
    # Агрегатор
    "MusicAggregator",
    "SearchStrategy",
    "ServiceConfig"
]


def create_music_aggregator() -> MusicAggregator:
    """Создание настроенного агрегатора музыкальных сервисов"""
    return MusicAggregator()


async def test_all_services():
    """Тестирование всех музыкальных сервисов"""
    print("🎵 Тестирование музыкальных сервисов...")
    
    async with create_music_aggregator() as aggregator:
        # Проверка здоровья всех сервисов
        health_results = await aggregator.health_check_all()
        
        print("\n📊 Состояние сервисов:")
        for service, health in health_results.items():
            status = health.get('status', 'unknown')
            emoji = "✅" if status == 'healthy' else "❌" if status == 'unhealthy' else "⚠️"
            print(f"  {emoji} {service}: {status}")
            
            if health.get('error'):
                print(f"    Ошибка: {health['error']}")
        
        # Тестовый поиск
        print(f"\n🔍 Тестовый поиск...")
        test_queries = ["imagine dragons believer", "billie eilish", "test"]
        
        for query in test_queries:
            print(f"\n  Запрос: '{query}'")
            results = await aggregator.search(query, limit=5)
            
            if results:
                print(f"    Найдено: {len(results)} результатов")
                for i, result in enumerate(results[:3], 1):
                    print(f"    {i}. {result.artist} - {result.title} ({result.source.value})")
                    if result.download_url:
                        print(f"       📥 Ссылка доступна")
            else:
                print(f"    Результатов не найдено")
        
        # Статистика сервисов
        print(f"\n📈 Статистика сервисов:")
        stats = aggregator.get_service_stats()
        
        for service, service_stats in stats.items():
            print(f"  {service}:")
            print(f"    Поисков: {service_stats['total_searches']}")
            print(f"    Успешность: {service_stats['success_rate']:.1%}")
            print(f"    Здоровье: {service_stats['health_score']:.2f}")
            print(f"    Ср. время: {service_stats['avg_response_time']:.2f}с")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_all_services())