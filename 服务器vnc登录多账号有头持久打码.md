# 服务器 VNC 登录多账号有头持久打码

## 重启/启动流程

```sh
cd /www/wwwroot/flow2api
docker rm -f flow2api-headed
find browser_data -name "SingletonLock" -o -name "SingletonCookie" -o -name "SingletonSocket" | xargs rm -f
docker compose -f docker-compose.headed.yml up -d --build
```

**说明：**
1. `docker rm -f` — 强制删除旧容器
2. `find ... | xargs rm -f` — 清理 Chrome 锁文件（**关键步骤**，不清理会导致浏览器启动失败）
3. `docker compose up -d --build` — 重新构建镜像并后台启动

**注意：不要用 `docker compose restart`**，必须先删容器、清锁文件再重新 up。

## 数据持久化

重启**不会丢失**数据：
- 浏览器登录态保存在宿主机 `browser_data/` 目录，通过 volume 挂载
- 数据库保存在宿主机 `data/` 目录
- 配置文件 `config/setting.toml` 也是挂载的

## VNC 连接

- 地址：`服务器IP:5900`（无密码）
- 如果连不上，检查防火墙是否放行了 5900 端口：`ufw allow 5900/tcp`
- 连接后可看到两个 Chrome 窗口，分别对应两个 Google 账号
- 在各自窗口里登录 Google 后，ST 自动刷新才能正常工作

## 新增账号

1. 打开管理页面 `http://服务器IP:1234/manage`
2. 添加新的 token（需要填入 ST、email 等信息）
3. 系统会根据 token 的 `email` 字段自动创建独立的浏览器实例
4. 添加后需要重启容器（按上面的重启流程）
5. 重启后 VNC 连接进去，在新弹出的 Chrome 窗口里登录对应的 Google 账号

**当前账号：**
- id=1: jamiemcconnell707@gmail.com (Pro, PAYGATE_TIER_ONE)
- id=2: z39@durisate.click (Ult, PAYGATE_TIER_TWO)

## 查看日志

```sh
docker logs flow2api-headed --tail 20
```

成功标志：
```
✓ Browser captcha resident mode started for xxx@xxx (project: xxx...)
✓ Browser captcha: 2 account(s) initialized
✓ Server running on http://0.0.0.0:1234
```
