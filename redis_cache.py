"""Redis-based caching for the scraper."""
from __future__ import annotations

import os
import json
import logging
import time
from datetime import timedelta
from typing import Any, Callable, Optional, TypeVar, cast

import redis
from redis.exceptions import RedisError

from dotenv import load_dotenv
load_dotenv()

# Global flag to enable/disable Redis, get from env
config = {
    "use_redis": os.getenv("USE_REDIS", "true").lower() in ("true", "1", "t", "y", "yes"),
    "redis_host": os.getenv("REDIS_HOST", "localhost"),
    "redis_port": int(os.getenv("REDIS_PORT", "6379")),
    "redis_db": int(os.getenv("REDIS_DB", "0")),
    "redis_password": os.getenv("REDIS_PASSWORD", None),
    "redis_default_ttl": int(os.getenv("REDIS_DEFAULT_TTL", "3600")),
    "redis_prefix": os.getenv("REDIS_PREFIX", "flac_scrapper:"),
}
USE_REDIS = config["use_redis"]

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Type variable for generic function return type
T = TypeVar('T')

class RedisCache:
    """A simple Redis-based cache with TTL support."""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        default_ttl: int = 3600,  # 1 hour default TTL
        prefix: str = "flac_scrapper:",
    ) -> None:
        """Initialize the Redis cache.
        
        Args:
            host: Redis server hostname
            port: Redis server port
            db: Redis database number
            password: Redis password if required
            default_ttl: Default TTL in seconds for cached items
            prefix: Prefix for all Redis keys
        """
        self.default_ttl = default_ttl
        self.prefix = prefix
        self.use_redis = USE_REDIS
        self._cache = {}  # Fallback in-memory cache
        self.redis = None
        
        if not self.use_redis:
            logger.warning("Redis is disabled. Using in-memory cache instead.")
            return
            
        try:
            self.redis = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            # Test the connection
            self.redis.ping()
            logger.info("Connected to Redis server")
        except RedisError as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to in-memory cache.")
            self.use_redis = False
            raise
    
    def _get_key(self, key: str) -> str:
        """Get the full Redis key with prefix."""
        return f"{self.prefix}{key}"
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the cache."""
        if not self.use_redis or self.redis is None:
            return self._cache.get(key, default)
            
        try:
            value = self.redis.get(self._get_key(key))
            if value is not None:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return default
        except RedisError as e:
            logger.warning(f"Redis get failed: {e}")
            return self._cache.get(key, default)
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """Set a value in the cache with optional TTL."""
        if not self.use_redis or self.redis is None:
            self._cache[key] = value
            return True
            
        try:
            if isinstance(value, (str, int, float, bool)):
                serialized = str(value)
            else:
                serialized = json.dumps(value)
            
            ttl = ttl if ttl is not None else self.default_ttl
            return self.redis.set(
                self._get_key(key),
                serialized,
                ex=ttl,
            )
        except (TypeError, RedisError) as e:
            logger.error(f"Redis set error: {e}")
            self._cache[key] = value
            return False
    
    def delete(self, *keys: str) -> int:
        """Delete one or more keys from the cache.
        
        Args:
            *keys: One or more keys to delete
            
        Returns:
            Number of keys that were deleted
        """
        if not self.use_redis or self.redis is None:
            count = 0
            for key in keys:
                if key in self._cache:
                    del self._cache[key]
                    count += 1
            return count
            
        try:
            # Convert keys to full Redis keys
            redis_keys = [self._get_key(key) for key in keys]
            return self.redis.delete(*redis_keys)
        except RedisError as e:
            logger.warning(f"Redis delete failed: {e}")
            # Fall back to in-memory cache
            count = 0
            for key in keys:
                if key in self._cache:
                    del self._cache[key]
                    count += 1
            return count
    
    def clear(self) -> None:
        """Clear all keys with the current prefix."""
        if self.use_redis and self.redis is not None:
            try:
                for key in self.redis.keys(f"{self.prefix}*"):
                    self.redis.delete(key)
            except RedisError as e:
                logger.warning(f"Redis clear failed: {e}")
        self._cache.clear()
    
    def cached(
        self,
        ttl: int = 3600,
        key_func: Optional[Callable[..., str]] = None
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator to cache function results."""
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                # Generate cache key
                cache_key = key_func(*args, **kwargs) if key_func else func.__name__
                
                # Try to get from cache
                cached = self.get(cache_key)
                if cached is not None:
                    return cast(T, cached)
                
                # Call the function and cache the result
                result = func(*args, **kwargs)
                self.set(cache_key, result, ttl=ttl)
                return result
                
            return wrapper
        return decorator
    
    def invalidate(self, key: str) -> None:
        """Invalidate a specific key."""
        self.delete(key)
    
    def get_ttl(self, key: str) -> int:
        """Get the TTL for a key in seconds."""
        if not self.use_redis or self.redis is None:
            return -1
        
        try:
            ttl = self.redis.ttl(self._get_key(key))
            return ttl if ttl is not None else -2
        except RedisError as e:
            logger.error(f"Redis TTL error: {e}")
            return -2
    
    def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        if not self.use_redis or self.redis is None:
            return key in self._cache
        
        try:
            return bool(self.redis.exists(self._get_key(key)))
        except RedisError as e:
            logger.error(f"Redis exists error: {e}")
            return False


# Global Redis cache instance
cache = RedisCache()


def get_redis_cache() -> RedisCache:
    """Get the global Redis cache instance."""
    return cache


def clear_redis_cache() -> None:
    """Clear the entire Redis cache for this application."""
    cache.clear()


# Example usage:
if __name__ == "__main__":
    # Example of using the cache
    @cache.cached(ttl=300)
    def expensive_operation(x: int, y: int) -> int:
        print("Performing expensive operation...")
        time.sleep(1)
        return x + y
    
    # First call - will be slow
    print(expensive_operation(2, 3))  # Will print "Performing expensive operation..." then 5
    
    # Second call with same arguments - will be fast (from cache)
    print(expensive_operation(2, 3))  # Will print 5 (from cache)
