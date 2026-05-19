# 网络登录工具 - 插件化版本
# 主程序只提供框架，插件全权负责协议

## 项目结构

```
test/
├── main.py                  # 主程序入口
├── plugin_base.py           # 插件基类 + 协议处理器接口
├── plugin_loader.py         # 插件加载器
├── config_manager.py        # 配置管理器（YAML + 迁移）
├── utils.py                 # 工具函数（从旧代码迁移）
├── config/
│   └── network_config.yaml  # 配置文件
└── plugins/
    └── portal_plugin.py     # 示例插件：通用 Portal 协议
```

## 运行方式

```bash
cd test
python main.py
```

## 插件开发

1. 在 `plugins/` 目录创建新 `.py` 文件
2. 导出 `Plugin` 类，继承 `ProtocolPlugin`
3. 实现 `name`、`description`、`create_config_widget`、`create_handler`
4. 重启主程序自动加载

## 配置格式

```yaml
Settings:
  auto_reconnect: true
  check_interval: 60
  current_plugin: "portal"

plugin_configs:
  portal:
    url: "..."
    userName: "..."
    pwd: "..."
```
