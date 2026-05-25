"""示例插件：通用 Portal 协议插件

基于原代码的 LoginWorker 和 Portal 登录逻辑实现。
网卡绑定功能由本插件全权负责。
"""
import sys
import os

# 确保可以导入父目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QLineEdit, QComboBox, QCheckBox,
                                QGroupBox, QFormLayout, QPushButton, QSpinBox)
from PySide6.QtCore import Qt, QTimer

from plugin_base import ProtocolPlugin, ProtocolHandler
from utils import send_http_via_socket, check_network_connectivity, get_network_interfaces


class PortalHandler(ProtocolHandler):
    """Portal 协议处理器

    bind_ip 从 plugin_config 中动态读取（插件自己管理）。
    支持格式：网卡名 "eno2"、"auto"、或旧格式 "eno2 (172.16.27.188)"。
    每次调用 login/check_online 时动态查当前 IP。
    """

    def __init__(self, global_settings: dict, plugin_config: dict, bind_ip: str):
        self.global_settings = global_settings
        self.plugin_config = plugin_config
        # 从配置中获取网卡名或 IP
        raw_bind = plugin_config.get('bind_ip', 'auto')
        self._configured_bind = raw_bind  # 保存原始配置值（网卡名或 auto）

    def _get_current_bind_ip(self) -> str | None:
        """动态获取当前可用的 bind_ip

        如果配置的网卡存在，返回其当前 IP；否则返回 None（auto）。
        """
        if self._configured_bind == 'auto' or not self._configured_bind:
            return None

        interfaces = get_network_interfaces()

        # 配置的网卡名存在，返回其当前 IP
        if self._configured_bind in interfaces:
            return interfaces[self._configured_bind]

        # 配置的已经是纯 IP，检查是否仍然有效
        if self._configured_bind in interfaces.values():
            return self._configured_bind

        # 网卡不存在，回退
        return None

    def check_online(self) -> bool:
        """检测是否已在线"""
        test_url = self.plugin_config.get('test_url', 'http://www.baidu.com')
        timeout = self.plugin_config.get('test_timeout', 5)
        force_bind = self.plugin_config.get('force_bind_check', False)
        bind_ip = self._get_current_bind_ip() if force_bind else None
        return check_network_connectivity(test_url, bind_ip, timeout)

    def login(self) -> tuple[bool, str]:
        """执行 Portal 登录"""
        try:
            login_url = self.plugin_config.get('url', '')
            if not login_url or 'YOUR_' in login_url:
                return False, "请先配置登录 URL"

            login_data = {
                "opr": self.plugin_config.get('opr', 'pwdLogin'),
                "userName": self.plugin_config.get('userName', ''),
                "pwd": self.plugin_config.get('pwd', ''),
                "auth_tag": self.plugin_config.get('auth_tag', 'TIMESTAMP'),
                "rememberPwd": self.plugin_config.get('remember_pwd', '0')
            }

            headers = self.plugin_config.get('headers', {})
            if 'Host' not in headers:
                from urllib.parse import urlparse
                parsed = urlparse(login_url)
                headers['Host'] = parsed.hostname or ''
            if 'Origin' not in headers:
                headers['Origin'] = f"{headers.get('Host', '')}"

            # 动态获取当前 bind_ip
            bind_ip = self._get_current_bind_ip()

            status_code, response_text, _ = send_http_via_socket(
                'POST', login_url, data=login_data, headers=headers,
                bind_ip=bind_ip, timeout=10
            )

            if status_code == 200:
                lower_text = response_text.lower()
                if 'success' in lower_text or 'logon success' in lower_text:
                    return True, "登录成功"
                else:
                    return False, f"登录响应: {response_text[:100]}"
            else:
                return False, f"HTTP 状态码: {status_code}"

        except Exception as e:
            return False, f"错误: {str(e)}"

    def logout(self) -> tuple[bool, str]:
        """执行登出（Portal 通常不需要显式登出）"""
        return True, "Portal 协议无需显式登出"


class PortalConfigWidget(QWidget):
    """Portal 插件配置控件

    网卡绑定由本插件管理：
    - 网卡选择下拉框（自动/具体网卡）
    - 实时保存 bind_ip 到 plugin_configs.portal.bind_ip
    - 修改后防抖写入配置文件
    """

    def __init__(self, plugin_config: dict, config_path: str):
        super().__init__()
        self.plugin_config = plugin_config
        self.config_path = config_path
        self.config_manager = None
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_config)

        # 当前实际可用的 bind_ip（运行时动态计算）
        self._current_bind_ip: str | None = None

        # 网卡IP动态更新定时器（每3秒检查一次网卡IP是否变化）
        self.interface_update_timer = QTimer()
        self.interface_update_timer.timeout.connect(self._update_interface_info)
        self.interface_update_timer.start(3000)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        # ===== 网卡绑定组（插件专属） =====
        iface_group = QGroupBox("网卡绑定")
        iface_layout = QFormLayout(iface_group)

        self.interface_combo = QComboBox()
        self.interface_combo.addItem("自动", "auto")
        interfaces = get_network_interfaces()
        for name, ip in interfaces.items():
            self.interface_combo.addItem(f"{name} ({ip})", name)

        current_bind = self.plugin_config.get('bind_ip', 'auto')
        if current_bind == 'auto':
            self.interface_combo.setCurrentIndex(0)
        else:
            idx = self.interface_combo.findData(current_bind)
            if idx >= 0:
                self.interface_combo.setCurrentIndex(idx)

        self.interface_combo.currentIndexChanged.connect(self._on_interface_changed)
        iface_layout.addRow("选择网卡:", self.interface_combo)

        layout.addWidget(iface_group)

        # ===== 网络检测设置组 =====
        detect_group = QGroupBox("网络检测设置")
        detect_layout = QFormLayout(detect_group)

        self.test_url_input = QLineEdit()
        self.test_url_input.setText(self.plugin_config.get('test_url', 'http://www.baidu.com'))
        self.test_url_input.setPlaceholderText("例如: http://www.baidu.com")
        self.test_url_input.textChanged.connect(self._on_detect_changed)
        detect_layout.addRow("检测 URL:", self.test_url_input)

        self.test_timeout_spin = QSpinBox()
        self.test_timeout_spin.setRange(1, 60)
        self.test_timeout_spin.setValue(self.plugin_config.get('test_timeout', 5))
        self.test_timeout_spin.setSuffix(" 秒")
        self.test_timeout_spin.valueChanged.connect(self._on_detect_changed)
        detect_layout.addRow("检测超时:", self.test_timeout_spin)

        self.force_bind_check = QCheckBox("强制绑定网卡检测")
        self.force_bind_check.setChecked(self.plugin_config.get('force_bind_check', False))
        self.force_bind_check.setToolTip("开启后网络检测会绑定到指定网卡 IP；关闭则使用系统默认路由检测\n关闭可解决绑定网卡后检测失败但实际网络正常的问题")
        self.force_bind_check.stateChanged.connect(self._on_detect_changed)
        detect_layout.addRow("", self.force_bind_check)

        layout.addWidget(detect_group)

        # ===== 配置说明 =====
        info_label = QLabel("Portal 协议配置在 YAML 文件中编辑，修改后程序自动热更新。")
        info_label.setStyleSheet("color: blue; font-weight: bold;")
        layout.addWidget(info_label)

        # ===== 按钮区 =====
        button_layout = QHBoxLayout()

        self.edit_config_btn = QPushButton("编辑配置文件")
        self.edit_config_btn.clicked.connect(self._edit_config)
        button_layout.addWidget(self.edit_config_btn)

        self.edit_template_btn = QPushButton("查看模板文件")
        self.edit_template_btn.clicked.connect(self._edit_template)
        button_layout.addWidget(self.edit_template_btn)

        layout.addLayout(button_layout)

        # ===== 当前配置摘要 =====
        summary_label = QLabel(
            f"当前配置摘要：\n"
            f"  URL: {self.plugin_config.get('url', '未设置')}\n"
            f"  用户名: {self.plugin_config.get('userName', '未设置')}\n"
            f"  认证类型: {self.plugin_config.get('opr', '未设置')}\n"
            f"  网卡绑定: {self.plugin_config.get('bind_ip', 'auto')}"
        )
        summary_label.setStyleSheet("color: gray;")
        layout.addWidget(summary_label)

        help_label = QLabel("提示：网卡绑定修改后自动保存，配置文件修改后程序自动热更新。")
        help_label.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(help_label)

    def _on_interface_changed(self, text=None):
        """网卡选择变化 → 更新插件配置并防抖保存

        配置中保存的是网卡名（如 "eno2"），不是 IP。
        运行时动态查 IP，网卡消失后自动回退 auto，重新出现后自动恢复。
        """
        self.plugin_config['bind_ip'] = self.interface_combo.currentData()
        self._save_timer.stop()
        self._save_timer.start(300)

    def _on_detect_changed(self):
        """检测 URL/超时/强制绑定变化 → 更新插件配置并防抖保存"""
        self.plugin_config['test_url'] = self.test_url_input.text().strip()
        self.plugin_config['test_timeout'] = self.test_timeout_spin.value()
        self.plugin_config['force_bind_check'] = self.force_bind_check.isChecked()
        self._save_timer.stop()
        self._save_timer.start(300)

    def _get_bind_ip(self) -> str | None:
        """根据配置的网卡名获取当前可用的 IP

        如果配置的网卡不存在，返回 None（回退到 auto）。
        """
        configured = self.plugin_config.get('bind_ip', 'auto')
        if configured == 'auto' or not configured:
            return None

        interfaces = get_network_interfaces()

        # 配置的网卡名存在，返回其当前 IP
        if configured in interfaces:
            return interfaces[configured]

        # 配置的已经是纯 IP，检查是否仍然有效
        if configured in interfaces.values():
            return configured

        # 网卡不存在，回退
        return None

    def _update_interface_info(self):
        """定时更新网卡信息和IP（每3秒）

        功能：
        - 刷新网卡列表（网卡可能插拔或IP变化）
        - 如果配置的网卡不存在，bind_ip 回退到 None（但不修改配置）
        - 如果配置的网卡重新出现，自动恢复
        - 更新下拉框显示（IP 可能已变化）
        - 如果实际 bind_ip 变化，更新状态显示
        """
        # 计算当前实际可用的 bind_ip
        new_bind_ip = self._get_bind_ip()
        old_bind_ip = self._current_bind_ip
        self._current_bind_ip = new_bind_ip

        # 获取当前网卡列表
        current_interfaces = get_network_interfaces()

        # 刷新下拉框（内部已根据 plugin_config['bind_ip'] 恢复选择）
        self._refresh_interface_combo(current_interfaces)

        # 如果实际 bind_ip 变化了，通知主程序更新状态
        if old_bind_ip != new_bind_ip:
            # 通过信号通知主程序（如果需要）
            print(f"[PortalConfigWidget] 网卡IP变化: {old_bind_ip} → {new_bind_ip}")

    def _refresh_interface_combo(self, current_interfaces: dict):
        """刷新网卡下拉框，恢复配置中的 bind_ip 而非 UI 当前值"""
        configured_bind = self.plugin_config.get('bind_ip', 'auto')

        self.interface_combo.blockSignals(True)
        self.interface_combo.clear()
        self.interface_combo.addItem("自动", "auto")
        for name, ip in current_interfaces.items():
            self.interface_combo.addItem(f"{name} ({ip})", name)

        # 恢复配置中的 bind_ip
        if configured_bind == 'auto':
            self.interface_combo.setCurrentIndex(0)
        else:
            idx = self.interface_combo.findData(configured_bind)
            if idx >= 0:
                self.interface_combo.setCurrentIndex(idx)

        self.interface_combo.blockSignals(False)

    def _save_config(self):
        """将插件配置写入 YAML 文件（通过 ConfigManager）"""
        if self.config_manager is not None:
            self.config_manager.save()
            print(f"[PortalConfigWidget] 已保存网卡绑定: {self.plugin_config.get('bind_ip')}")
        else:
            print("[PortalConfigWidget] 无法保存：config_manager 未设置")

    def _edit_config(self):
        try:
            os.startfile(self.config_path)
        except Exception:
            try:
                os.system(f"xdg-open {self.config_path}")
            except Exception:
                try:
                    os.system(f"open {self.config_path}")
                except Exception:
                    print(f"无法打开配置文件: {self.config_path}")

    def _edit_template(self):
        template_path = self.config_path.replace('.yaml', '_template.yaml')
        try:
            os.startfile(template_path)
        except Exception:
            try:
                os.system(f"xdg-open {template_path}")
            except Exception:
                try:
                    os.system(f"open {template_path}")
                except Exception:
                    print(f"无法打开模板文件: {template_path}")


class Plugin(ProtocolPlugin):
    """Portal 插件入口类"""

    @property
    def name(self) -> str:
        return "通用 Portal 协议"

    @property
    def plugin_id(self) -> str:
        return "portal"

    @property
    def description(self) -> str:
        return "基于 HTTP 表单提交的校园/企业 Portal 认证协议（网卡绑定由本插件管理）"

    def create_config_widget(self, plugin_config: dict, config_path: str) -> QWidget:
        return PortalConfigWidget(plugin_config, config_path)

    def create_handler(self, global_settings: dict, plugin_config: dict,
                       bind_ip: str) -> ProtocolHandler:
        # bind_ip 参数由主程序传入 None，实际从 plugin_config 中读取
        return PortalHandler(global_settings, plugin_config, bind_ip)
