"""配置管理器 - 处理 YAML 配置文件的加载、保存和迁移"""
import os
import yaml
from typing import Any


class ConfigManager:
    """配置文件管理器

    负责：
    - 加载/创建配置文件
    - 自动创建模板文件（首次启动时）
    - 配置迁移（旧格式 → 新插件格式）
    - 配置实时保存（插件直接调用）
    - 配置热更新检测
    """

    def __init__(self, config_path: str = "config/network_config.yaml"):
        self.config_path = config_path
        self.config: dict[str, Any] = {}
        self._last_modified: float = 0
        self.template_path = config_path.replace('.yaml', '_template.yaml')

    def load_or_create(self) -> dict[str, Any]:
        """加载或创建配置文件，返回完整配置"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        # 自动检查并创建模板文件
        self._ensure_template_exists()

        if not os.path.exists(self.config_path):
            self._create_default_config()

        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # 配置迁移：旧格式 → 新插件格式
        self._migrate_old_config()

        self._last_modified = os.path.getmtime(self.config_path)
        return self.config

    def _ensure_template_exists(self):
        """自动检查并创建模板文件（如果不存在）"""
        if not os.path.exists(self.template_path):
            self._create_template_config()

    def _create_template_config(self):
        """创建模板文件（带注释的参考配置）"""
        template_content = '''# ============================================================
# 总体设置（控制自动重连、检测、网卡等行为）
# ============================================================
Settings:
  auto_reconnect: true                # 是否自动重连（网络断开后自动重新认证）
  check_interval: 60                  # 网络连通性检查间隔（秒），每60秒检测一次是否在线
  current_plugin: portal              # 当前使用的认证插件类型（portal 认证）
  forced_auto_reconnect: false        # 是否强制自动重连
  forced_periodic_login: false        # 是否强制周期性登录
  network_interface: <YOUR_NETWORK_INTERFACE>   # 使用的网络接口名称（例如 eth0、wlan0）
  periodic_login_enabled: true        # 是否启用周期性登录
  periodic_login_interval: 600        # 周期性登录间隔（秒）
  test_timeout: 5                     # 网络检测超时时间（秒）
  test_url: http://www.baidu.com      # 网络连通性检测 URL

# ============================================================
# portal 认证插件专用配置（登录参数、请求头、URL 等）
# ============================================================
plugin_configs:
  portal:
    # ---------- 认证参数 ----------
    auth_tag: '<TIMESTAMP_PLACEHOLDER>'     # 认证时间戳（原值已打码）
    opr: pwdLogin                           # 操作类型：密码登录
    pwd: '<ENCRYPTED_PASSWORD_PLACEHOLDER>' # 加密后的密码（已打码）
    remember_pwd: '1'                       # 是否记住密码
    url: http://<PORTAL_SERVER_IP>/ac_portal/login.php   # 登录接口 URL（IP 已打码）
    userName: '<YOUR_USERNAME>'             # 登录用户名（已打码）

    # ---------- HTTP 请求头 ----------
    headers:
      Accept: '*/*'
      Accept-Encoding: gzip, deflate
      Accept-Language: zh-CN,en-US;q=0.7,en;q=0.3
      Cache-Control: no-cache
      Connection: keep-alive
      Content-Type: application/x-www-form-urlencoded; charset=UTF-8
      Cookie: '<SESSION_COOKIE_PLACEHOLDER>'   # 会话 Cookie（原值已打码）
      DNT: '1'
      Host: '<PORTAL_SERVER_IP>'               # 目标主机 IP（已打码）
      Origin: http://<PORTAL_SERVER_IP>        # 请求来源（IP 已打码）
      Pragma: no-cache
      Referer: http://<PORTAL_SERVER_IP>/ac_portal/default/pc.html?template=default&tabs=pwd&vlanid=0&_ID_=0&switch_url=&url=http://<PORTAL_SERVER_IP>/homepage/index.html&controller_type=&mac=<MAC_ADDRESS_PLACEHOLDER>
      User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0
      X-Requested-With: XMLHttpRequest
'''

        with open(self.template_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        print(f"[ConfigManager] 已创建模板文件: {self.template_path}")

    def _create_default_config(self):
        """创建默认配置文件（新插件格式）"""
        default_config = {
            "Settings": {
                "auto_reconnect": True,
                "check_interval": 60,
                "test_url": "http://www.baidu.com",
                "test_timeout": 5,
                "periodic_login_interval": 0,
                "periodic_login_enabled": False,
                "forced_auto_reconnect": False,
                "forced_periodic_login": False,
                "current_plugin": "portal"  # 当前激活的插件
            },
            "plugin_configs": {
                "portal": {
                    "bind_ip": "auto",
                    "url": "http://YOUR_LOGIN_SERVER_URL/ac_portal/login.php",
                    "opr": "pwdLogin",
                    "userName": "YOUR_USERNAME",
                    "pwd": "YOUR_PASSWORD",
                    "auth_tag": "TIMESTAMP",
                    "remember_pwd": "0",
                    "headers": {
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                }
            }
        }

        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, default_flow_style=False,
                      allow_unicode=True, indent=2)
        print(f"[ConfigManager] 已创建默认配置文件: {self.config_path}")

    def _migrate_old_config(self):
        """配置迁移：将旧格式（Login/Headers/Settings）迁移到新格式

        旧格式：
            Login: {...}
            Headers: {...}
            Settings: {...}
            network_interface: ...

        新格式：
            Settings: {...}
            plugin_configs:
                portal:
                    bind_ip: ...
                    url: ...
                    opr: ...
                    headers: {...}
        """
        if "plugin_configs" not in self.config:
            self.config["plugin_configs"] = {}

        # 检查是否存在旧格式的 Login 和 Headers
        if "Login" in self.config or "Headers" in self.config:
            # 迁移到 portal 插件配置（使用 plugin_id）
            if "portal" not in self.config["plugin_configs"]:
                portal_config = {}

                # 迁移 Login 部分
                if "Login" in self.config:
                    login = self.config["Login"]
                    portal_config["url"] = login.get("url", "")
                    portal_config["opr"] = login.get("opr", "pwdLogin")
                    portal_config["userName"] = login.get("userName", "")
                    portal_config["pwd"] = login.get("pwd", "")
                    portal_config["auth_tag"] = login.get("auth_tag", "TIMESTAMP")
                    portal_config["remember_pwd"] = login.get("rememberPwd", "0")

                # 迁移 Headers 部分
                if "Headers" in self.config:
                    portal_config["headers"] = self.config["Headers"]

                # 迁移网卡绑定：从 Settings.network_interface → plugin_configs.portal.bind_ip
                if "Settings" in self.config:
                    old_iface = self.config["Settings"].get("network_interface", "auto")
                    portal_config["bind_ip"] = old_iface

                self.config["plugin_configs"]["portal"] = portal_config

                # 设置当前插件为 portal
                if "current_plugin" not in self.config.get("Settings", {}):
                    if "Settings" not in self.config:
                        self.config["Settings"] = {}
                    self.config["Settings"]["current_plugin"] = "portal"

                # 保存迁移后的配置
                self.save()
                print(f"[ConfigManager] 配置已迁移：旧格式 → 新插件格式")

    def save(self):
        """保存配置到文件"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, default_flow_style=False,
                      allow_unicode=True, indent=2)

    def update_plugin_config(self, plugin_id: str, key: str, value: Any):
        """更新某个插件的配置项并实时保存

        Args:
            plugin_id: 插件 ID
            key: 配置键
            value: 配置值
        """
        if "plugin_configs" not in self.config:
            self.config["plugin_configs"] = {}
        if plugin_id not in self.config["plugin_configs"]:
            self.config["plugin_configs"][plugin_id] = {}

        self.config["plugin_configs"][plugin_id][key] = value
        self.save()

    def get_plugin_config(self, plugin_id: str) -> dict:
        """获取某个插件的配置（返回可变引用）"""
        if "plugin_configs" not in self.config:
            self.config["plugin_configs"] = {}
        if plugin_id not in self.config["plugin_configs"]:
            self.config["plugin_configs"][plugin_id] = {}
        return self.config["plugin_configs"][plugin_id]

    def get_global_settings(self) -> dict:
        """获取全局设置"""
        if "Settings" not in self.config:
            self.config["Settings"] = {}
        return self.config["Settings"]

    def check_update(self) -> bool:
        """检查配置文件是否被外部修改

        Returns:
            True 表示配置已更新
        """
        try:
            current_modified = os.path.getmtime(self.config_path)
            if current_modified != self._last_modified:
                self._last_modified = current_modified
                return True
        except Exception:
            pass
        return False

    def reload(self) -> dict[str, Any]:
        """强制重新加载配置文件"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        self._last_modified = os.path.getmtime(self.config_path)
        return self.config
