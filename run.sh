docker rm -f flow2api-headed
find browser_data -name "SingletonLock" -o -name "SingletonCookie" -o -name "SingletonSocket" | xargs rm -f
docker compose -f docker-compose.headed.yml up -d --build